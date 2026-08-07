"""Instancia compartilhada do servidor MCP 'epo-ops'.

Vive num modulo proprio para quebrar o ciclo de import entre epo_mcp.py (que
tambem registra topico.py para o servidor local) e os modulos de logica
(topico.py), que precisam do mesmo `mcp` para decorar suas tools com
`@mcp.tool()`. Mesmo padrao de inpi/mcp_app.py.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("epo-ops")
