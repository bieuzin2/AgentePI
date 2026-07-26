"""Carrega os CSVs de dados abertos do INPI num DuckDB local.

Fonte: https://dadosabertos.inpi.gov.br/index/patentes/ (atualizado diariamente).

    python inpi/ingest.py            # carrega o que ja esta em inpi/data/raw/
    python inpi/ingest.py --baixar   # baixa os CSVs antes de carregar

Idempotente: recria as tabelas do zero a cada execucao. Os CSVs sao a fonte de
verdade; o .duckdb e derivado e pode ser jogado fora sem perda.

NOTA DE REDE: revistas.inpi.gov.br e busca.inpi.gov.br derrubam o handshake TLS
(ver referencias/fontes-rpi.md), mas dadosabertos.inpi.gov.br responde normal.
E de la que vem tudo isto.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb

BASE_URL = "https://dadosabertos.inpi.gov.br/download/patentes/"

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


def baixar() -> int:
    """Baixa os CSVs do INPI para inpi/data/raw/.

    Grava em arquivo temporario e so renomeia no fim: uma queda no meio deixaria
    um CSV truncado que o read_csv_auto carregaria em silencio, e a base ficaria
    faltando processos sem ninguem perceber.
    """
    import httpx

    BRUTO.mkdir(parents=True, exist_ok=True)
    total = 0
    for arquivo in TABELAS.values():
        destino = BRUTO / arquivo
        parcial = destino.with_suffix(destino.suffix + ".parcial")
        t0 = time.time()
        try:
            with httpx.stream("GET", BASE_URL + arquivo, timeout=120,
                              follow_redirects=True) as r:
                r.raise_for_status()
                esperado = int(r.headers.get("content-length") or 0)
                with parcial.open("wb") as fh:
                    for bloco in r.iter_bytes(1 << 20):
                        fh.write(bloco)
            baixado = parcial.stat().st_size
            if esperado and baixado != esperado:
                parcial.unlink(missing_ok=True)
                print(f"  {arquivo:<34} FALHOU: {baixado:,} de {esperado:,} bytes",
                      flush=True)
                return 1
            parcial.replace(destino)
            total += baixado
            print(f"  {arquivo:<34} {baixado/1e6:>7.1f} MB  {time.time()-t0:5.1f}s",
                  flush=True)
        except Exception as e:
            parcial.unlink(missing_ok=True)
            print(f"  {arquivo:<34} FALHOU: {type(e).__name__}: {str(e)[:70]}", flush=True)
            return 1
    print(f"\n  total baixado: {total/1e9:.2f} GB\n", flush=True)
    return 0


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
    if "--baixar" in sys.argv:
        print(f"Baixando de {BASE_URL}", flush=True)
        if baixar() != 0:
            return 1

    faltando = [f for f in TABELAS.values() if not (BRUTO / f).exists()]
    if faltando:
        print(f"CSVs ausentes em {BRUTO}:", ", ".join(faltando))
        print("Rode com --baixar, ou baixe de "
              "https://dadosabertos.inpi.gov.br/index/patentes/")
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
