"""Conexão compartilhada com o banco local de enriquecimento (claims/citações).

PRIORIDADE: arquivo local primeiro, MotherDuck só como fallback -- MESMO fix
de inpi/db.py (commit 4602bad), pela MESMA causa: qualquer import que carregue
o .env (ex.: inpi.familia_epo, importado por inpi_mcp -> oposicoes) põe
MOTHERDUCK_TOKEN no ambiente do processo inteiro. Sem esta ordem invertida,
QUALQUER código que importe inpi_mcp antes de chamar o harness de
enriquecimento passa a gravar/ler no MotherDuck (que so sincroniza manualmente
e pode estar semanas atrasado) em vez do arquivo local recém-escrito --
silenciosamente, sem erro. Confirmado ao vivo verificando o fix de claims
cross-jurisdição deste plano: 'import inpi.inpi_mcp' sozinho já publica o
token no ambiente antes de qualquer chamada de tool.

Em produção (Render), onde não existe arquivo local, o fallback MotherDuck
continua sendo a ÚNICA fonte -- por isso ele não foi removido, só reordenado.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent
BANCO = RAIZ / "data" / "enriquecimento.duckdb"

_con: duckdb.DuckDBPyConnection | None = None

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS claims (
        numero_normalizado VARCHAR,
        fonte VARCHAR,
        doc_id VARCHAR,
        reivindicacoes_json VARCHAR,
        status VARCHAR,
        mensagem VARCHAR,
        atualizado_em VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS citacoes (
        numero_normalizado VARCHAR,
        tipo VARCHAR,
        doc_citado VARCHAR,
        fonte VARCHAR,
        atualizado_em VARCHAR
    )
    """,
)


def con() -> duckdb.DuckDBPyConnection:
    """Conexão única por processo. Sem PRIMARY KEY nas tabelas de propósito --
    store.py garante unicidade por DELETE+INSERT, o que evita depender de
    comportamento de UPSERT/ON CONFLICT (que difere entre arquivo local e
    MotherDuck) para algo tão simples quanto "a última leitura vence"."""
    global _con
    if _con is None:
        token = os.environ.get("MOTHERDUCK_TOKEN")
        if BANCO.exists():
            BANCO.parent.mkdir(parents=True, exist_ok=True)
            _con = duckdb.connect(str(BANCO))
        elif token:
            _con = duckdb.connect(f"md:?motherduck_token={token}")
            _con.execute("CREATE DATABASE IF NOT EXISTS enriquecimento")
            _con.execute("USE enriquecimento")
        else:
            BANCO.parent.mkdir(parents=True, exist_ok=True)
            _con = duckdb.connect(str(BANCO))
        for stmt in _DDL:
            _con.execute(stmt)
    return _con


def fechar() -> None:
    """Só para testes: força reabrir a conexão (novo arquivo/DB) na próxima
    chamada a con()."""
    global _con
    if _con is not None:
        _con.close()
        _con = None
