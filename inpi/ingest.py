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
        print(f"  {tabela:<14} {n:>12,} linhas   {time.time()-t0:5.1f}s{dup}")

    # Indices que sustentam as consultas do servidor MCP. numero_inpi e a chave
    # natural do processo e aparece em toda pergunta de acompanhamento.
    for tabela in ("despachos", "biblio", "conteudo", "depositantes", "ipc"):
        con.execute(f"CREATE INDEX IF NOT EXISTS ix_{tabela}_num ON {tabela}(numero_inpi)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_despachos_data ON despachos(data_rpi)")

    print(f"\nBanco: {BANCO}  ({BANCO.stat().st_size/1e6:.0f} MB)")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
