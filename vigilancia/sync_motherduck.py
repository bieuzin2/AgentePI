"""Sobe o banco INPI local para o MotherDuck apos a ingestao semanal.

Sem isto o agente do Teams responde com dados congelados. Roda como passo
final de vigilancia.executar -- e NUNCA pode derrubar a ingestao local: falha
aqui e logada e devolvida, nao propagada.

O que sobe e o que nao sobe (decisao, nao esquecimento):
- `inpi` (inpi.duckdb): substituicao COMPLETA -- so a ingestao local escreve.
- `carteira` (tarefas/radar_watermark): NAO sincroniza. O agente remoto cria
  tarefas direto na nuvem; sobrescrever com o local apagaria essas tarefas.
  (A antiga tabela `casos`/carteira ingerida foi removida na Fase G.)
- `landscape_cache`: nao sincroniza. O cache remoto vive e cresce na nuvem.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
from dotenv import load_dotenv

from inpi.db import BANCO as BANCO_INPI

# Task Scheduler nao herda o .env -- carrega aqui, como epo/epo_mcp.py faz.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def sincronizar() -> dict:
    """Sobe inpi (completo) para o MotherDuck. Nunca levanta: devolve
    {"ok": bool, ...} para o chamador logar."""
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
            return {"ok": True, "enviados": enviados}
        finally:
            con.close()
    except Exception as exc:  # rede/MotherDuck fora: loga, nao derruba a ingestao
        return {"ok": False, "mensagem": f"{type(exc).__name__}: {exc}"}
