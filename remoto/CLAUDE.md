# remoto/ — Superfície MCP para o M365 Copilot

## Purpose
Reempacota, num único servidor HTTP, um subconjunto curado das tools dos servidores
locais (`inpi`, `epo`, `landscape`) para o agente do **Copilot Studio / Teams** consumir.
Não reimplementa lógica — importa as funções já decoradas e as registra em `TOOLS`.

## Stack & entrypoints
- `servidor_mcp.py` — FastMCP `streamable_http_app` (Starlette), stateless. `montar_app()`
  monta o app; `TOOLS` (linha ~87) é a lista curada. Deploy: Render (free tier).
- `test_servidor_mcp.py` — testa `_chave_valida` (função pura, sem subir servidor).

## Commands
- Subir local: `API_KEY_AGENTE_PI=xxx .venv/Scripts/python remoto/servidor_mcp.py`
- Health (sem auth): `GET /health` → `{ok, tools}`. Usado pelo keep-alive contra cold start.

## Architecture
- Auth obrigatória (`_ExigeChaveDeAPI`): todo request precisa de `Authorization: Bearer` ou
  `X-API-Key` = `API_KEY_AGENTE_PI`; sem a env var o servidor **recusa subir** (fail-safe).
- Adicionar tool à superfície = importar a função + incluí-la em `TOOLS`. `uspto` e `busca`
  ficam de fora de propósito (uspto é servidor externo; `busca_anterioridade` é pesada — pode
  estourar o timeout ~100s do Copilot Studio; exponha só se aceitar a latência).

## Regra de ouro: MCP vs internet (NÃO misturar fontes)
O agente do Copilot pode ter acesso à internet. Dado de patente/carteira vem **sempre** do MCP.
A web só é acionada quando uma tool devolve `encontrado=false` (ex.: `inpi_responsavel_pi`), e o
resultado web deve ser **rotulado como internet**, nunca fundido com dado do MCP nem apresentado
como dado do INPI. Configure isso na instrução de sistema do agente no Copilot Studio.

## Security & gotchas
- Nunca commitar `API_KEY_AGENTE_PI`.
- O banco no container Render vem do MotherDuck (o arquivo local não existe lá) — garanta que o
  sync subiu as tabelas necessárias (ver `vigilancia/sync_motherduck.py`), inclusive as `ficha_*`.

## Context routing
Mapa tool→tabela e gotcha das tabelas derivadas: ver `inpi/CLAUDE.md`.
