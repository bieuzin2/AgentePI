"""Instancia compartilhada do servidor MCP 'landscape' e o helper cache-first
`_rodar`. Vive num modulo proprio para quebrar o ciclo de import entre
landscape_mcp.py (que so registra) e landscape/carteira_bridge.py, que precisa
do mesmo `mcp`/`_rodar` para decorar `landscape_carteira` -- mesmo padrao de
inpi/mcp_app.py.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from landscape import cache
from landscape.bigquery_client import TETO_BYTES_PADRAO, cliente

mcp = FastMCP("landscape")


def _rodar(nome: str, fn, args: dict, *, teto_bytes: int = TETO_BYTES_PADRAO,
           confirmar_acima_10gb: bool = False) -> dict:
    """Cache-first: le do DuckDB (30 dias) antes de bater no BigQuery.

    teto_bytes/confirmar_acima_10gb controlam o teto de 10GB do BigQuery e
    ficam FORA da chave de cache -- so afetam se a consulta roda, nao o que
    ela retorna, entao nao devem gerar entradas de cache diferentes.
    """
    cacheado = cache.obter(nome, args)
    if cacheado is not None:
        cacheado["cache"] = True
        return cacheado
    resultado = fn(cliente(), teto_bytes=teto_bytes,
                    confirmar_acima_10gb=confirmar_acima_10gb, **args)
    resultado["cache"] = False
    cache.salvar(nome, args, resultado)
    return resultado
