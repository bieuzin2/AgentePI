"""Ponte carteira x landscape: quais tecnologias (CPC) dominam a carteira de
um cliente, e o que a inteligencia de mercado (BigQuery) mostra sobre elas --
plano-v2 Fase 4.

Conexoes DuckDB EFEMERAS e read-only, abertas e fechadas dentro da funcao: os
bancos inpi.duckdb e carteira.duckdb ja tem conexao singleton nos seus proprios
modulos (inpi.db.con, inpi.carteira.con), mas aquelas vivem no processo do
servidor MCP 'inpi'. Este modulo roda dentro do servidor 'landscape' -- abrir
conexao propria evita depender do processo alheio e evita lock cruzado.

IPC ~ CPC no nivel de subclasse (4 caracteres, ex. 'A61K'): os dois sistemas
compartilham a mesma hierarquia ate esse nivel; divergem so em grupos/subgrupos
mais profundos. Por isso 'top_cpc' aqui e, na pratica, o prefixo IPC mais
frequente na carteira, usado como prefixo CPC nas consultas ao landscape.
"""

from __future__ import annotations

import os
from collections import Counter

import duckdb

from inpi.carteira import BANCO as BANCO_CARTEIRA
from inpi.carteira import conectar_carteira
from inpi.db import BANCO as BANCO_INPI
from landscape import consultas
from landscape.mcp_app import _rodar, mcp


def _conectar_inpi() -> duckdb.DuckDBPyConnection:
    """Conexao efemera ao banco INPI (nao o singleton de inpi.db -- este
    modulo roda no processo do servidor 'landscape', e abrir aqui evita
    depender do processo do servidor 'inpi')."""
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if token:
        c = duckdb.connect(f"md:?motherduck_token={token}")
        c.execute("USE inpi")
        return c
    return duckdb.connect(str(BANCO_INPI), read_only=True)


def _numeros_br_da_carteira(cliente: str) -> list[str]:
    if not os.environ.get("MOTHERDUCK_TOKEN") and not BANCO_CARTEIRA.exists():
        return []
    con = conectar_carteira(BANCO_CARTEIRA, read_only=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT numero_norm FROM casos WHERE cliente = ? AND jurisdicao = 'BR'",
            [cliente]).fetchall()]
    finally:
        con.close()


def cpcs_da_carteira(cliente: str, top: int = 3) -> dict:
    """Prefixos CPC (4 caracteres) mais frequentes na carteira BR de um cliente.

    USE QUANDO: for escolher em qual tecnologia rodar uma consulta landscape
    para ESTE cliente especificamente, sem adivinhar a mao.
    """
    brs = _numeros_br_da_carteira(cliente)
    if not brs:
        return {
            "erro": True,
            "mensagem": (
                f"Nenhum caso BR na carteira de {cliente!r}. Rode carteira_ingerir "
                "ou carteira_descobrir antes."
            ),
        }
    if not os.environ.get("MOTHERDUCK_TOKEN") and not BANCO_INPI.exists():
        return {"erro": True, "mensagem": f"Banco INPI ausente: {BANCO_INPI}."}

    con = _conectar_inpi()
    try:
        linhas = con.execute(
            "SELECT simbolo FROM ipc WHERE numero_inpi IN (SELECT unnest(?::VARCHAR[]))",
            [brs],
        ).fetchall()
    finally:
        con.close()

    contagem = Counter(
        simbolo[:4] for (simbolo,) in linhas if simbolo and len(simbolo) >= 4
    )
    top = max(1, min(top, 10))
    return {
        "cliente": cliente,
        "casos_br_na_carteira": len(brs),
        "casos_com_ipc": sum(contagem.values()),
        "cpc_distintos": len(contagem),
        "top_cpc": [cpc for cpc, _ in contagem.most_common(top)],
        "distribuicao": dict(contagem.most_common(20)),
        "nota": (
            "IPC ~ CPC ate o nivel de subclasse (4 caracteres) -- os codigos "
            "aqui sao prefixo IPC da carteira, usados como prefixo CPC no "
            "landscape (Google Patents Public Data classifica por CPC)."
        ),
    }


@mcp.tool()
def landscape_carteira(cliente: str, top_cpc: int = 3, pais: str | None = None,
                       desde: str | None = None, ate: str | None = None,
                       confirmar_acima_10gb: bool = False) -> dict:
    """Cruza a carteira BR de um cliente com inteligencia de mercado (BigQuery):
    para as tecnologias (CPC) que mais aparecem na carteira dele, mostra quem
    mais deposita no mundo -- concorrencia que o cliente provavelmente nao ve
    olhando so a propria carteira.

    USE QUANDO: preparar reuniao de cliente com contexto competitivo, sem o
    cliente precisar dizer em qual tecnologia olhar.

    Args:
        cliente: nome do cliente na carteira (carteira_ingerir/carteira_descobrir).
        top_cpc: quantos prefixos CPC mais frequentes consultar (1 a 10).
        pais: filtro de pais opcional nas consultas de landscape.
        desde/ate: 'AAAA-MM-DD' opcionais.
        confirmar_acima_10gb: True para permitir consulta acima do teto de
            10GB do BigQuery (o teto se aplica a cada consulta individual).
    """
    base = cpcs_da_carteira(cliente, top=top_cpc)
    if base.get("erro"):
        return base

    por_cpc = {}
    for cpc in base["top_cpc"]:
        top_titulares = _rodar(
            "top_titulares", consultas.top_titulares,
            {"cpc_prefix": cpc, "pais": pais, "desde": desde, "ate": ate, "limite": 10},
            confirmar_acima_10gb=confirmar_acima_10gb,
        )
        evolucao = _rodar(
            "evolucao_temporal", consultas.evolucao_temporal,
            {"cpc_prefix": cpc, "pais": pais, "desde": desde, "ate": ate},
            confirmar_acima_10gb=confirmar_acima_10gb,
        )
        por_cpc[cpc] = {
            "casos_da_carteira_nesse_cpc": base["distribuicao"].get(cpc, 0),
            "top_titulares_mundiais": top_titulares.get("linhas", []),
            "evolucao_temporal": evolucao.get("linhas", []),
        }

    return {
        "cliente": cliente,
        "casos_br_na_carteira": base["casos_br_na_carteira"],
        "top_cpc_da_carteira": base["top_cpc"],
        "por_cpc": por_cpc,
        "fonte_landscape": consultas.FONTE,
        "nota": base["nota"],
        "aviso": (
            "Consultas landscape tem atraso de meses (Google Patents Public "
            "Data) e sao contagem de documentos, nao veredito de mercado. Cada "
            "prefixo CPC dispara ate 2 consultas ao BigQuery (cacheadas por 30 "
            "dias)."
        ),
    }
