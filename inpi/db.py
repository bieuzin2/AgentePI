"""Conexao compartilhada com o banco de dados abertos do INPI (inpi.duckdb).

Somente-leitura, cacheada por processo -- e a mesma conexao usada pelo servidor
MCP (inpi_mcp.py) e por quem agrega sobre ela (panorama_carteira.py), evitando
abrir o banco duas vezes.

Com MOTHERDUCK_TOKEN no ambiente (Fase 6, servidor remoto no Render -- o
container nao tem o arquivo local), conecta no banco 'inpi' hospedado no
MotherDuck em vez do arquivo local. Migrado uma vez com
'CREATE DATABASE inpi FROM inpi/data/inpi.duckdb'; a sincronizacao continua
manual ate existir um passo automatico pos-ingestao.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent
BANCO = RAIZ / "data" / "inpi.duckdb"

_con: duckdb.DuckDBPyConnection | None = None


def con() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        token = os.environ.get("MOTHERDUCK_TOKEN")
        if token:
            _con = duckdb.connect(f"md:?motherduck_token={token}")
            _con.execute("USE inpi")
        elif BANCO.exists():
            _con = duckdb.connect(str(BANCO), read_only=True)
        else:
            raise RuntimeError(
                f"Banco ausente: {BANCO}. Baixe os CSVs de "
                "https://dadosabertos.inpi.gov.br/index/patentes/ para inpi/data/raw/ "
                "e rode: python inpi/ingest.py -- ou configure MOTHERDUCK_TOKEN."
            )
    return _con
