# Agente PI no Copilot Studio — instruções de conexão (Fase 6)

## Servidor remoto

- Código: `remoto/servidor_mcp.py` (FastMCP, transporte streamable HTTP).
- Deploy: Render Web Service `AgentePI`, plano Free, branch `main`,
  deploy automático a cada push.
- URL do serviço: `https://agentepi.onrender.com`
- URL do endpoint MCP: `https://agentepi.onrender.com/mcp`
- Health check (sem auth, para keep-alive): `https://agentepi.onrender.com/health`

## Autenticação

Chave de API na env var `API_KEY_AGENTE_PI` do Render. O servidor aceita a
chave em **qualquer um** destes headers (não documentado qual o Copilot
Studio usa — testar os dois na conexão real):

- `Authorization: Bearer <chave>`
- `X-API-Key: <chave>`

No formulário "Adicionar servidor MCP" do Copilot Studio:
- **Nome**: Agente PI
- **Descrição**: Consulta processual INPI, prazos/anuidades, métricas de
  gestão de portfólio (gargalos, financeiro, saúde de carteira, radar de
  prospecção) e inteligência de mercado (landscape via BigQuery).
- **URL do servidor**: `https://agentepi.onrender.com/mcp`
- **Autenticação**: Chave de API — colar o valor de `API_KEY_AGENTE_PI`.

## Limite conhecido (pendência antes do piloto funcionar de fato)

O servidor está no ar, mas as tools **ainda não funcionam remotamente**:
elas dependem de `inpi.duckdb`/`carteira.duckdb`/`landscape_cache.duckdb`
locais (gitignored, não existem no container do Render) e de ADC do Google
Cloud (login pessoal, não existe no Render). Toda chamada de tool remota
hoje devolve o erro claro que `inpi/db.py` e `landscape/bigquery_client.py`
já levantam localmente ("banco ausente" / "credenciais ausentes") — nunca
falha em silêncio, mas também não responde ainda.

Pendente para o piloto funcionar ponta a ponta:
1. **MotherDuck** (free tier 10GB): criar conta, gerar token, subir
   `inpi.duckdb`/`carteira.duckdb`/`landscape_cache.duckdb`, trocar a string
   de conexão em `inpi/db.py`/`inpi/carteira.py`/`landscape/cache.py` por
   env var `MOTHERDUCK_TOKEN`. Sincronização: passo pós-ingestão em
   `vigilancia/executar.py` (ingestão semanal continua local).
2. **Service account do BigQuery**: projeto GCP `patentes-landscape`, papel
   BigQuery Job User + Data Viewer, JSON em env var
   `GOOGLE_APPLICATION_CREDENTIALS_JSON` no Render.
3. Confirmar qual header de auth o Copilot Studio de fato envia (ajustar
   `remoto/servidor_mcp.py::_ExigeChaveDeAPI` se for nenhum dos dois testados).

## Onboarding do agente (system prompt / instruções)

Já preenchido no agente "Agente PI" criado no Copilot Studio (rascunho, não
publicado nem compartilhado). Ver seção 3 do plano de implementação para o
texto completo de instruções e exemplos de prompt por categoria.
