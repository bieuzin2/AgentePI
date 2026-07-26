"""Carrega os CSVs de dados abertos do INPI num DuckDB local.

Fonte: https://dadosabertos.inpi.gov.br/index/patentes/ (atualizado diariamente).
Baixe os CSVs para inpi/data/raw/ e rode:  python inpi/ingest.py

Idempotente: recria as tabelas do zero a cada execucao. Os CSVs sao a fonte de
verdade; o .duckdb e derivado e pode ser jogado fora sem perda.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent
BRUTO = RAIZ / "data" / "raw"
BANCO = RAIZ / "data" / "inpi.duckdb"

# nome_da_tabela -> arquivo CSV
TABELAS = {
    "despachos": "PATENTES_DESPACHOS.csv",
    "biblio": "PATENTES_DADOS_BIBLIOGRAFICOS.csv",
    "conteudo": "PATENTES_CONTEUDO.csv",
    "depositantes": "PATENTES_DEPOSITANTES.csv",
    "inventores": "PATENTES_INVENTORES.csv",
    "ipc": "PATENTES_CLASSIFICACAO_IPC.csv",
    "prioridades": "PATENTES_PRIORIDADES.csv",
    "procuradores": "PATENTES_PROCURADORES.csv",
    "vinculos": "PATENTES_VINCULOS.csv",
    "renumeracoes": "PATENTES_RENUMERACOES.csv",
}


def _materializa_nomes(con) -> None:
    """Cria a tabela de chaves normalizadas de ESCRITORIO.

    So escritorio, de proposito. Sao 17.521 grafias de procurador para ~10 mil bancas
    reais -- a Clarke Modet sozinha aparece em 42 formas, e sem agrupar toda
    estatistica de mercado sai errada e a carteira sai fragmentada. Materializar aqui
    custa ~75 s e vale.

    Titular NAO e materializado: sao ~500 mil nomes distintos, o unnest de uma lista
    desse tamanho nao terminava em 5+ minutos, e o ganho e menor -- quem pergunta por
    "Petrobras" e atendido por ILIKE. Onde o agrupamento importa (prospeccao), a
    normalizacao roda em Python sobre as poucas dezenas de linhas do resultado.
    """
    import sys
    sys.path.insert(0, str(RAIZ))
    from escritorios import normalizar

    for tabela, coluna, nova in (
        ("procuradores", "procurador", "escritorios"),
    ):
        t0 = time.time()
        distintos = [
            r[0] for r in con.execute(
                f"SELECT DISTINCT {coluna} FROM {tabela} WHERE {coluna} IS NOT NULL"
            ).fetchall()
        ]
        chaves = [normalizar(n) for n in distintos]
        con.execute(f"DROP TABLE IF EXISTS {nova}")
        # Uma query com dois arrays, nao executemany. Com ~500 mil titulares o
        # INSERT linha a linha nao terminava: o WAL crescia 2 MB/min e a carga
        # passava de uma hora. unnest resolve em segundos.
        con.execute(
            f"""CREATE TABLE {nova} AS
                SELECT unnest(?::VARCHAR[]) AS original, unnest(?::VARCHAR[]) AS chave""",
            [distintos, chaves],
        )
        pares = distintos
        n_chaves = con.execute(f"SELECT count(DISTINCT chave) FROM {nova}").fetchone()[0]
        print(f"  {nova:<14} {len(pares):>12,} grafias -> {n_chaves:,} chaves "
              f"(-{1 - n_chaves / max(len(pares), 1):.0%})   {time.time()-t0:5.1f}s",
              flush=True)


def main() -> int:
    faltando = [f for f in TABELAS.values() if not (BRUTO / f).exists()]
    if faltando:
        print(f"CSVs ausentes em {BRUTO}:", ", ".join(faltando))
        print("Baixe em https://dadosabertos.inpi.gov.br/index/patentes/")
        return 1

    BANCO.parent.mkdir(parents=True, exist_ok=True)
    # DROP TABLE nao devolve espaco ao arquivo: reingerir por cima quase dobrava o
    # .duckdb a cada rodada. Recriar do zero e mais simples que CHECKPOINT/VACUUM,
    # e o custo e baixo -- a carga inteira leva ~2 min.
    BANCO.unlink(missing_ok=True)
    con = duckdb.connect(str(BANCO))
    for tabela, arquivo in TABELAS.items():
        caminho = (BRUTO / arquivo).as_posix()
        t0 = time.time()
        con.execute(f"DROP TABLE IF EXISTS {tabela}")
        # SELECT DISTINCT nao e paranoia: os CSVs do INPI vem com linhas
        # integralmente repetidas na origem -- medimos 4 linhas identicas do mesmo
        # depositante, IPC 2x, inventores 3,3x em media. Sem deduplicar aqui, toda
        # ficha de processo sai com o titular repetido quatro vezes.
        con.execute(
            f"""CREATE TABLE {tabela} AS
                SELECT DISTINCT * FROM read_csv_auto('{caminho}', header=true,
                                                     sample_size=-1, ignore_errors=false)"""
        )
        n = con.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]
        bruto = con.execute(
            f"SELECT count(*) FROM read_csv_auto('{caminho}', header=true, sample_size=-1)"
        ).fetchone()[0]
        dup = f"  (-{bruto - n:,} duplicatas, {bruto / n:.2f}x)" if bruto > n else ""
        print(f"  {tabela:<14} {n:>12,} linhas   {time.time()-t0:5.1f}s{dup}", flush=True)

    # Sem CREATE INDEX de proposito. DuckDB e colunar: um scan filtrado de 5,3 milhoes
    # de linhas custa milissegundos, e o indice ART so ajuda em point lookup. Medido:
    # com indices em 8 tabelas a carga travava por mais de 20 minutos a 100% de CPU
    # (construcao de ART sobre VARCHAR); sem eles, termina em ~2 min e as consultas do
    # servidor respondem igual -- a carteira Petrobras sai em 2 s de qualquer jeito.
    _materializa_nomes(con)

    print(f"\nBanco: {BANCO}  ({BANCO.stat().st_size/1e6:.0f} MB)")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
