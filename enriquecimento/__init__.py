"""Enriquecimento de dados por fontes externas sem API oficial (ou com API
oficial que não cobre BR): reivindicações e citações.

Ver docs/superpowers/plans/2026-08-10-enriquecimento-copilot-fix.md para o
desenho completo. Resumo: roda LOCAL (nunca no MCP remoto do Render, que não
tem navegador), grava num DuckDB local espelhado no MotherDuck via
`enriquecimento.sync_motherduck`, e é chamado on-demand pelas MCP tools
`inpi_reivindicacoes` / `inpi_citacoes` (harness.py) -- nunca em lote/agendado.
"""
