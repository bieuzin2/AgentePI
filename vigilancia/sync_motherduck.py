"""Sobe os bancos locais para o MotherDuck apos a ingestao semanal.

Sem isto o agente do Teams responde com dados congelados na data do ultimo
upload manual. Roda como passo final de vigilancia.executar -- e NUNCA pode
derrubar a ingestao local: falha aqui e logada e devolvida, nao propagada.

O que sobe e o que nao sobe (decisao, nao esquecimento):
- `inpi` (inpi.duckdb): substituicao COMPLETA -- so a ingestao local escreve.
- `carteira`: SO a tabela `casos`. A tabela `tarefas` NAO e sobrescrita:
  o agente remoto cria tarefas direto na nuvem, e o arquivo local nao as tem
  -- substituir o banco inteiro apagaria tarefas criadas via Teams.
- `landscape_cache`: nao sincroniza. O cache remoto vive e cresce na nuvem;
  sobrescrever com o local so perderia entradas.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
from dotenv import load_dotenv

from inpi.carteira import BANCO as BANCO_CARTEIRA
from inpi.db import BANCO as BANCO_INPI

# Task Scheduler nao herda o .env -- carrega aqui, como epo/epo_mcp.py faz.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def sincronizar() -> dict:
    """Sobe inpi (completo) e carteira.casos para o MotherDuck. Nunca levanta:
    devolve {"ok": bool, ...} para o chamador logar."""
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if not token:
        return {"ok": False, "pulado": True,
                "mensagem": "MOTHERDUCK_TOKEN ausente -- sync pulado."}
    try:
        con = duckdb.connect(f"md:?motherduck_token={token}")
        try:
            enviados = []
            if BANCO_INPI.exists():
                caminho = str(BANCO_INPI).replace("'", "''")
                con.execute(f"CREATE OR REPLACE DATABASE inpi FROM '{caminho}'")
                enviados.append("inpi (completo)")
            if BANCO_CARTEIRA.exists():
                caminho = str(BANCO_CARTEIRA).replace("'", "''")
                con.execute(f"ATTACH '{caminho}' AS carteira_local (READ_ONLY)")
                con.execute("CREATE OR REPLACE TABLE carteira.casos AS "
                            "SELECT * FROM carteira_local.casos")
                enviados.append("carteira.casos")
            return {"ok": True, "enviados": enviados}
        finally:
            con.close()
    except Exception as exc:  # rede/MotherDuck fora: loga, nao derruba a ingestao
        return {"ok": False, "mensagem": f"{type(exc).__name__}: {exc}"}
