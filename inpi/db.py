"""Conexao compartilhada com o banco de dados abertos do INPI (inpi.duckdb).

Somente-leitura, cacheada por processo -- e a mesma conexao usada pelo servidor
MCP (inpi_mcp.py) e por quem agrega sobre ela (panorama_carteira.py), evitando
abrir o banco duas vezes.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent
BANCO = RAIZ / "data" / "inpi.duckdb"

_con: duckdb.DuckDBPyConnection | None = None


def con() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        if not BANCO.exists():
            raise RuntimeError(
                f"Banco ausente: {BANCO}. Baixe os CSVs de "
                "https://dadosabertos.inpi.gov.br/index/patentes/ para inpi/data/raw/ "
                "e rode: python inpi/ingest.py"
            )
        _con = duckdb.connect(str(BANCO), read_only=True)
    return _con
