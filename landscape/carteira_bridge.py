"""Ponte titular x landscape: quais tecnologias (CPC) dominam o portfolio BR de
um titular, e o que a inteligencia de mercado (BigQuery) mostra sobre elas --
Fase 4, reescrito na Fase G para rodar do TITULAR REAL (base INPI), sem
depender de upload manual de carteira.

Conexao DuckDB EFEMERA e read-only, aberta e fechada dentro da funcao: o banco
inpi.duckdb ja tem conexao singleton em inpi.db.con, mas aquela vive no processo
do servidor MCP 'inpi'. Este modulo roda dentro do servidor 'landscape' -- abrir
conexao propria evita depender do processo alheio e evita lock cruzado. Por isso
a resolucao nome->chave e as agregacoes rodam por esta conexao, nao por
titulares.chave_de (que usa o singleton do processo 'inpi').

IPC ~ CPC no nivel de subclasse (4 caracteres, ex. 'A61K'): os dois sistemas
compartilham a mesma hierarquia ate esse nivel; divergem so em grupos/subgrupos
mais profundos. Por isso 'top_cpc' aqui e, na pratica, o prefixo IPC mais
frequente no portfolio, usado como prefixo CPC nas consultas ao landscape.
"""

from __future__ import annotations

import os
from collections import Counter

import duckdb

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


def _ipc_do_titular(con: duckdb.DuckDBPyConnection, nome: str) -> tuple[str | None, list[str]]:
    """Chave canonica do titular (mais processada) e os simbolos IPC de todo o
    seu portfolio BR -- tudo por UMA conexao (a efemera do processo landscape)."""
    chave_row = con.execute(
        """SELECT t.chave FROM depositantes dp JOIN titulares t ON t.original = dp.depositante
           WHERE dp.depositante ILIKE ? GROUP BY t.chave
           ORDER BY count(DISTINCT dp.numero_inpi) DESC LIMIT 1""",
        [f"%{nome.strip()}%"],
    ).fetchone()
    if not chave_row:
        return None, []
    chave = chave_row[0]
    simbolos = [r[0] for r in con.execute(
        """SELECT i.simbolo FROM ipc i
           WHERE i.numero_inpi IN (
             SELECT DISTINCT dp.numero_inpi FROM depositantes dp
             JOIN titulares t ON t.original = dp.depositante WHERE t.chave = ?)""",
        [chave],
    ).fetchall()]
    return chave, simbolos


def cpcs_da_carteira(cliente: str, top: int = 3) -> dict:
    """Prefixos CPC (4 caracteres) mais frequentes no portfolio BR de um titular.

    USE QUANDO: for escolher em qual tecnologia rodar uma consulta landscape
    para ESTE titular especificamente, sem adivinhar a mao.
    """
    if not os.environ.get("MOTHERDUCK_TOKEN") and not BANCO_INPI.exists():
        return {"erro": True, "mensagem": f"Banco INPI ausente: {BANCO_INPI}."}

    con = _conectar_inpi()
    try:
        chave, simbolos = _ipc_do_titular(con, cliente)
    finally:
        con.close()

    if not chave:
        return {
            "erro": True,
            "mensagem": (f"Nenhum titular casou com {cliente!r} na base INPI. "
                         "Confira a grafia ou use inpi_titular_resolver."),
        }

    contagem = Counter(s[:4] for s in simbolos if s and len(s) >= 4)
    top = max(1, min(top, 10))
    return {
        "cliente": cliente,
        "chave_titular": chave,
        "casos_com_ipc": sum(contagem.values()),
        "cpc_distintos": len(contagem),
        "top_cpc": [cpc for cpc, _ in contagem.most_common(top)],
        "distribuicao": dict(contagem.most_common(20)),
        "nota": (
            "IPC ~ CPC ate o nivel de subclasse (4 caracteres) -- os codigos "
            "aqui sao prefixo IPC do portfolio BR do titular, usados como prefixo "
            "CPC no landscape (Google Patents Public Data classifica por CPC)."
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
        cliente: nome do titular (resolvido na base INPI, sem upload).
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
            "processos_do_titular_nesse_cpc": base["distribuicao"].get(cpc, 0),
            "top_titulares_mundiais": top_titulares.get("linhas", []),
            "evolucao_temporal": evolucao.get("linhas", []),
        }

    from inpi.titulares import resolver

    return {
        "cliente": cliente,
        "normalizacao": resolver(base.get("chave_titular")),
        "top_cpc_do_titular": base["top_cpc"],
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
