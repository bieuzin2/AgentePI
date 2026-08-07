"""Conexao ao banco fisico carteira.duckdb -- neutro, sem esquema de negocio.

Este arquivo existe porque `tarefas.py` (tabela `tarefas`, lembretes) e
`radar.py` (tabela `radar_watermark`) vivem no mesmo arquivo fisico. Na Fase G
o antigo sistema de "carteira ingerida" (tabela `casos`, inpi/carteira.py) foi
removido -- nada mais depende de upload manual de portfolio -- mas o arquivo
fisico segue hospedando tarefas/radar. So a CONEXAO ficou aqui; cada tabela e
criada por quem a usa (tarefas.py::ESQUEMA, radar.py::ESQUEMA_RADAR).

MotherDuck (MOTHERDUCK_TOKEN no ambiente) tem prioridade sobre o arquivo local.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent

BANCO = RAIZ / "data" / "carteira.duckdb"


def conectar_carteira(banco: Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Conexao ao banco de carteira: MotherDuck (MOTHERDUCK_TOKEN) ou o arquivo
    local passado em 'banco'. Compartilhada por tarefas.py e radar.py.

    'banco' recebe o CAMINHO, nao um default fixo aqui: cada chamador passa a
    sua propria variavel BANCO/BANCO_TAREFAS de modulo, para que testes que
    monkeypatcham essa variavel continuem valendo mesmo com a conexao
    centralizada aqui."""
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if token:
        c = duckdb.connect(f"md:?motherduck_token={token}")
        c.execute("CREATE DATABASE IF NOT EXISTS carteira")
        c.execute("USE carteira")
        return c
    banco = banco if banco is not None else BANCO
    banco.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(banco), read_only=read_only)
