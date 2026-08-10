"""Sobe o banco local de enriquecimento para o MotherDuck.

Mesmo padrão de vigilancia/sync_motherduck.py: substituição COMPLETA do banco
'enriquecimento' no MotherDuck a partir do arquivo local. Sem isto, o
enriquecimento feito nesta máquina (dev) nunca chega ao MCP remoto do Render
-- que só lê o banco hospedado (ver enriquecimento/db.py). NUNCA levanta:
falha aqui é logada e devolvida, nunca propagada.

Quando MOTHERDUCK_TOKEN já está setado (uso normal em produção/CI), db.py
grava direto no banco hospedado e este módulo não tem nada a fazer -- ele só
importa para o fluxo local-primeiro-depois-sobe (dev na máquina do operador,
sem o token, testando contra o arquivo local antes de publicar).
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
from dotenv import load_dotenv

from enriquecimento.db import BANCO

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def sincronizar() -> dict:
    """Sobe o banco local de enriquecimento (completo) para o MotherDuck.
    Devolve {"ok": bool, ...} para o chamador logar -- nunca levanta."""
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if not token:
        return {"ok": False, "pulado": True,
                "mensagem": "MOTHERDUCK_TOKEN ausente -- sync pulado."}
    if not BANCO.exists():
        return {"ok": False, "pulado": True,
                "mensagem": f"{BANCO} ainda não existe -- nada para sincronizar."}
    try:
        con = duckdb.connect(f"md:?motherduck_token={token}")
        try:
            caminho = str(BANCO).replace("'", "''")
            con.execute(f"CREATE OR REPLACE DATABASE enriquecimento FROM '{caminho}'")
            return {"ok": True, "enviado": "enriquecimento (completo)"}
        finally:
            con.close()
    except Exception as exc:  # rede/MotherDuck fora: loga, não derruba o chamador
        return {"ok": False, "mensagem": f"{type(exc).__name__}: {exc}"}
