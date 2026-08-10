"""Conexao compartilhada com o banco de dados abertos do INPI (inpi.duckdb).

Somente-leitura, cacheada por processo -- e a mesma conexao usada pelo servidor
MCP (inpi_mcp.py) e por quem agrega sobre ela (panorama_carteira.py), evitando
abrir o banco duas vezes.

PRIORIDADE: arquivo local primeiro, MotherDuck so como fallback. O arquivo local
e sempre a copia mais fresca (e o que o ingest.py acabou de escrever); a copia no
MotherDuck e sincronizada manualmente ('CREATE DATABASE inpi FROM
inpi/data/inpi.duckdb') e pode ficar atrasada por semanas. MOTHERDUCK_TOKEN
existe no ambiente para o caso do servidor remoto no Render (Fase 6) -- o
container nao tem o arquivo local, entao MotherDuck e a UNICA fonte la. Mas
localmente o .env tambem costuma ter o token (usado por outras integracoes,
como o EPO), e QUALQUER import que carregue esse .env (ex.: inpi.familia_epo)
poe o token no ambiente do processo inteiro -- sem esta ordem invertida, isso
desviava silenciosamente toda consulta local para a copia desatualizada do
MotherDuck, mesmo com o arquivo local presente e correto. Foi assim que
'table biblio does not exist' apareceu em producao sem ninguem ter mudado nada
no banco: bastou `inpi_mcp.py` importar `oposicoes.py`, que importa
`familia_epo.py`, que chama `load_dotenv()`.
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
        if BANCO.exists():
            _con = duckdb.connect(str(BANCO), read_only=True)
        elif token:
            _con = duckdb.connect(f"md:?motherduck_token={token}")
            _con.execute("USE inpi")
        else:
            raise RuntimeError(
                f"Banco ausente: {BANCO}. Baixe os CSVs de "
                "https://dadosabertos.inpi.gov.br/index/patentes/ para inpi/data/raw/ "
                "e rode: python inpi/ingest.py -- ou configure MOTHERDUCK_TOKEN."
            )
    return _con
