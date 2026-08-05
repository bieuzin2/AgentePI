"""Instancia compartilhada do servidor MCP 'inpi'.

Vive num modulo proprio para quebrar o ciclo de import entre inpi_mcp.py (que so
registra) e os modulos de logica (consulta, prazos, mercado), que precisam do
mesmo `mcp` para decorar suas tools com `@mcp.tool()`.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("inpi")
