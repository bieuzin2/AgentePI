# inpi/ — Servidor MCP da base de dados abertos do INPI (DuckDB local)

## Purpose
Busca em texto de patente BR e acompanhamento processual, offline, sobre o dump semanal de
dados abertos do INPI. É o **hub** do projeto: cruza com EPO por import Python direto
(`inpi.familia_epo`, `epo.epo_mcp`), não por MCP-a-MCP.

## Stack & entrypoints
- `inpi_mcp.py` — registra as tools (importa a lógica dos submódulos) e é o entrypoint (`mcp.run()`).
- `mcp_app.py` — instância `FastMCP("inpi")` compartilhada (quebra ciclos de import).
- `db.py` — conexão read-only. Prioriza `inpi/data/inpi.duckdb`; cai para MotherDuck só se o
  arquivo não existir (container Render).

## Commands
- Recriar o banco: `python inpi/ingest.py` (lê CSVs de `inpi/data/raw/`, recria o `.duckdb` do zero).
- Testes: `python -m pytest inpi/ -q`.

## Architecture — mapa tool → tabelas
- Consulta processual: `inpi_processo` (biblio/despachos/procuradores/ipc **+ ficha_extras/
  ficha_peticoes/ficha_anuidades + renumeracoes/vinculos** quando existem), `inpi_busca_texto`,
  `inpi_busca_ipc`, `inpi_despachos_por_rpi`, `inpi_titular_resolver`, `inpi_portfolio_titular`.
- Prazos/anuidades: `inpi_anuidades` (PROJETA art. 84), `inpi_anuidades_pagas` (REALIZADO —
  ledger `ficha_anuidades`, por escritório/período; `anuidades_pagas.py`), `inpi_prazos_carteira`, `inpi_novidades`,
  `inpi_prazo_fase_nacional` (marco PCT 30/31m). Regras em `jurisdicoes.py`.
- Mercado/escritórios: `inpi_carteira`, `inpi_prospeccao`, `inpi_mercado`, `inpi_producao_escritorio`,
  `inpi_conflitos_identidade`, etc. (procuradores/escritorios/titulares/identidade_escritorio).
- Cruzam EPO: `carteira_saude`, `financeiro_projecao`, `cliente_dossie`, `carteira_oposicoes_ep`,
  `carteira_auditoria_vigencia`, `fila_semana`.
- Refinamento (novas): `inpi_reconciliar` (`reconciliacao.py` — cruza INPI×EPO×enriquecimento e
  MARCA divergências), `fto_dominio_publico` (`fto.py` — FTO/domínio público sob a LPI),
  `inpi_gaps_protecao` (`gaps_protecao.py` — pedidos perto do prazo PCT sem proteção em país
  importante), `inpi_responsavel_pi` (`inteligencia_mercado.py` — responsável de PI curado, ver
  regra MCP-vs-internet em `remoto/CLAUDE.md`).

## Security & gotchas
- **Banco pode estar PARCIAL.** As tabelas DERIVADAS (`titulares`, `escritorios`,
  `identidade_escritorio`, `ficha_anuidades`) só existem após um `python inpi/ingest.py` completo.
  Sem elas, tools que resolvem titular/escritório levantam `CatalogException` — rode o ingest
  completo antes de deploy. Código novo checa a existência da tabela (`consulta._tem_tabela`).
- Read-only: nunca escreva no `inpi.duckdb` a partir de uma tool.
- LGPD: saídas com pessoa física carregam aviso próprio (ver `mercado._AVISO_PESSOAL`).
- `panorama_carteira.py` está VIVO (alimenta `relatorio_html`/`painel_dados`/vigilância) — o
  `casos` que ele consulta é um CTE, não a tabela removida. Não podar.
