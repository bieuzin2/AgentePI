# Plano de Implementação — Agente de Patentes v2.0

> Executável pelo Claude Sonnet. Autocontido. Cada decisão tem justificativa. Idioma do projeto: português do Brasil.

## 1. Visão e Objetivos

**O que será**: assistente de IA para escritório de gestão de PI, operando dentro do Claude Code via MCP, com camada autônoma de scripts Python agendados (monitoramento, reingestão, projeções). Missão: **democratizar e otimizar o acesso à informação de PI** — busca, vigilância, prazos, inteligência competitiva.

**O que NÃO será** (limites acordados com o stakeholder):
- Não redige patentes nem pareceres formais — isso é trabalho dos profissionais da ClarkeModet. O agente entrega informação organizada (relatórios de busca, quadros de confronto, dashboards), não opinião assinável.
- Não é o docketing do escritório. Regra de ouro mantida: "o agente informa e confere; o controle é do procurador".
- Não dá veredito de patenteabilidade ("aparenta estar antecipada, sujeito à confirmação do examinador").
- Sem integrações pagas. Single-user, replicável com credenciais próprias.

## 2. Decisões Arquiteturais

**Arquitetura: híbrida Claude Code + scripts autônomos** (decidido com stakeholder).
- Claude Code = interface conversacional + cérebro analítico (skills existentes).
- Scripts Python agendados via **Windows Task Scheduler** = reingestão, monitoramento, projeções, geração de dashboard e e-mail. Rodam sem LLM; agente só interpreta resultados.
- Justificativa: zero custo novo (LLM via assinatura), autonomia real, sem infra web.

**Stack mantida**: Python 3.12, FastMCP, DuckDB, httpx, openpyxl, reportlab, Chart.js (HTML autocontido). Sem mudança — funcional e testada (91+ testes).

**Padrões**:
- Pacote Python de verdade (`pyproject.toml`, imports absolutos) — elimina os 12 `sys.path.insert`.
- Camada de dados separada de renderização: módulos `*_dados.py` retornam dicts/DataFrames; renderizadores (HTML/PDF/XLSX) só formatam.
- Toda fonte externa com cache local em disco.
- Saídas sempre com âncora tripla e proveniência (fonte + data de corte).

## 3. Fontes de Dados

| Fonte | Endpoint | Custo | Papel | Status |
|---|---|---|---|---|
| INPI Dados Abertos | CSVs semanais | grátis | verdade BR, 5,3M despachos | ligado |
| EPO OPS v3.2 | ops.epo.org | 4 GB/sem grátis | famílias INPADOC, status legal mundial, texto EP/WO | ligado, **falta cache** |
| USPTO PPUBS | ppubs.uspto.gov | grátis, sem chave | full-text US | ligado |
| USPTO ODP + PTAB | api.uspto.gov | grátis, chave ID.me | file wrapper, continuidade, assignments, litígios | **Gabriel cria chave** (account.uspto.gov/api-manager) |
| Google Patents BigQuery | `patents-public-data.patents.publications` | 1 TB/mês grátis | landscape macro 166M publicações | **novo — Gabriel cria projeto GCP** |
| OpenAlex | api.openalex.org | grátis, sem chave | NPL (literatura científica) para anterioridade | **novo** |
| PDFs INPI | portal busca.inpi.gov.br | grátis | reivindicações de documentos BR publicados | **novo** |

Fora de escopo: Lens.org (trial limitado), scraping de Espacenet (OPS já cobre), CNIPA direto.

**Estratégia de cache**: EPO → middleware Dogpile da lib `python-epo-ops-client` (já instalada, só ativar) + cache de famílias já existente em `familia_epo.py`. BigQuery → resultados salvos em DuckDB (`landscape_cache`) com TTL 30 dias. OpenAlex → cache httpx em disco. PDFs INPI → arquivos em `inpi/data/pdfs/`.

## 4. Módulos e Features

### 4.0 Fase 0 — Higiene e Refatoração (OBRIGATÓRIA, primeira)

Motivo: ~2.250 linhas de produção fora do git; god module; sem pacote; lixo no repo.

1. **Versionar código órfão**: `git add inpi/carteira.py inpi/panorama_carteira.py inpi/relatorio_html.py inpi/test_carteira.py inpi/referencias/` (novos) + commitar deleções staged dos ~36 arquivos de 0 byte.
2. **`.gitignore`**: adicionar `__pycache__/`, `*.duckdb`, `inpi/data/`, `.env`, padrões contra vazamento de redirect (`[0-9].[0-9]*`, etc. — na prática: revisar manualmente e treinar cuidado com `>` em comandos).
3. **Remover**: `inpi/src/`, `inpi/tests/`, `inpi/tools/` (vazios), `.claude-flow/` se não usado.
4. **Empacotar**: criar `pyproject.toml` na raiz com pacotes `inpi` e `epo`; instalar editable (`pip install -e .`); remover os 12 `sys.path.insert`; quebrar o import de `panorama_carteira` → `inpi_mcp` criando `inpi/db.py` com `con()` compartilhado.
5. **Modularizar `inpi_mcp.py`** (1.929 linhas → ~5 módulos, cortes já desenhados nos comentários internos):
   - `inpi/db.py` — conexões DuckDB (inpi + carteira)
   - `inpi/consulta.py` — consulta processual (L171-525 atual)
   - `inpi/prazos.py` — motor prazos/anuidades (L526-965)
   - `inpi/mercado.py` — inteligência mercado/escritórios (L1036-1760)
   - `inpi/inpi_mcp.py` — só registro das tools MCP, importando dos módulos acima. Docstrings de tool enxutas (narrativa de negócio migra para `docs/`).
6. **Ativar cache EPO**: middleware Dogpile em `epo/epo_mcp.py`, cache em `epo/data/cache.dbm`.
7. **Testes**: `pytest epo inpi -q` verde antes e depois de cada corte. Sem mudança de comportamento — refatoração pura.

Complexidade: M. Testes existentes são a rede de segurança.

### 4.1 Monitoramento Autônomo (prioridade 1 pós-Fase 0)

**Novo pacote `vigilancia/`**:
- `vigilancia/config.yaml` — watchlists: números da carteira, titulares concorrentes, IPCs vigiadas, e-mail destino.
- `vigilancia/reingestao.py` — baixa CSVs do INPI (reusa `inpi/ingest.py`), recarrega DuckDB, registra data de corte.
- `vigilancia/vigias.py` — 5 vigias, cada um retorna lista de alertas estruturados:
  1. **Watchlist carteira**: despachos novos nos casos vigiados desde última execução (diff por RPI). Inclui **detecção de anulação** — despacho `8.8`/`21.8`/`15.x` que referencia despacho anterior vira alerta vermelho (caso `PI0803071`).
  2. **Concorrentes**: novos depósitos/publicações/decisões por titular vigiado (reusa `inpi_portfolio_titular`).
  3. **IPCs**: novos depósitos nas classificações vigiadas (reusa `inpi_busca_ipc`).
  4. **Anuidades**: janela 90 dias da projeção art. 84 (reusa `inpi/anuidades.py`), diff vs semana anterior.
  5. **Exterior** (mensal, poupa quota): mudança de status legal INPADOC das famílias da carteira (reusa `familia_epo.py` + `epo_status_legal`).
- `vigilancia/executar.py` — orquestra: reingestão → vigias → grava alertas em `vigilancia/data/alertas.duckdb` + `alertas.md` → regenera dashboard → envia e-mail.
- `vigilancia/email_alerta.py` — SMTP Gmail (app password em `.env`: `SMTP_USER`, `SMTP_PASS`). Resumo HTML simples.
- **Agendamento**: script `scripts/instalar_agendamento.ps1` cria tarefa no Task Scheduler — terça 20h (pós-RPI) semanal; vigia 5 na primeira terça do mês.
- **Tool MCP nova**: `inpi_alertas` — agente lê alertas pendentes na conversa; marca como vistos.
- Testes: fixtures de RPIs consecutivas simulando despacho novo, anulação, anuidade entrando na janela.

Complexidade: M.

### 4.2 Projeção de Anuidades consolidada (junto com 4.1)

Já existe (`anuidades.py`, `quadro_global.py`). Evolução:
- Expor `inpi_anuidades` com saída sempre acompanhada de data-base, regra aplicada (art. 84/40/87) e despacho `16.1` como prova — padrão já documentado em `capacidades.md`.
- Integrar ao dashboard e ao vigia 4. Sem retrabalho de lógica.

Complexidade: P.

### 4.3 Dashboard do Escritório (evolução do `relatorio_html.py`)

- Extrair camada de dados: `inpi/painel_dados.py` retorna estrutura única consumida por HTML/PDF/XLSX (mata a triplicação de renderizadores).
- `relatorio_html.py` quebrado: `gerar()` de 476 linhas vira template + seções. Novas seções: alertas da semana, anuidades 90 dias, tarefas abertas, gráficos landscape.
- Regenerado automaticamente pelo `vigilancia/executar.py`; abre no navegador, zero servidor.
- Design: usar skill `ui-ux-pro-max` na implementação (obrigatório por CLAUDE.md para HTML).

Complexidade: M.

### 4.4 Pipeline de Busca de Anterioridade

**Novo `busca/pipeline.py`** + tool MCP `busca_anterioridade`:
1. Entrada: descrição da invenção (texto livre) + conceitos-chave opcionais.
2. Agente (via skill `analista-patentes-inpi`, já existente) decompõe em conceitos e sinônimos — isso fica no LLM, não no script.
3. Script executa em paralelo: INPI (título/resumo + IPC), EPO OPS (CQL), PPUBS (BRS), OpenAlex (NPL).
4. **Dedup por família INPADOC** (reusa `familia_epo.py`): resultados agrupados, um representante por família.
5. Saída estruturada: lista ranqueada (data de publicação vs data crítica, sobreposição de conceitos) + **estratégia de busca documentada** (queries executadas, fonte, nº de hits) — auditável, padrão de relatório de busca profissional.
- **Novo `busca/openalex.py`**: cliente httpx para api.openalex.org (`/works?search=...&filter=from_publication_date:...`), sem chave, cache em disco.
- Tool `busca_npl` separada para uso direto.
- Testes: mocks httpx por fonte; dedup com fixtures de famílias.

Complexidade: M.

### 4.5 PDFs INPI + Claim Chart BR

**Novo `inpi/pdf_inpi.py`**:
- Download de PDF público de pedido BR publicado (portal do INPI; endpoint de documento por número de processo — validar na implementação qual rota pública funciona sem login; fallback: instruir usuário a salvar PDF manualmente em `inpi/data/pdfs/`).
- Extração de texto: `pypdf` (novo dep); se PDF for imagem, reportar "requer OCR — fora de escopo v2.0" (OCR fica como extensão futura, evita dependência pesada de tesseract agora).
- Parser de seções: relatório descritivo / reivindicações / resumo (heurística por marcadores "REIVINDICAÇÕES", numeração "1.", "2.").
- Tool MCP `inpi_reivindicacoes` — retorna quadro reivindicatório estruturado.
- Com isso o claim chart BR (já suportado pela skill para US/EP) passa a funcionar para documentos BR.
- Testes: fixtures de PDFs reais pequenos (2-3 casos), parser de seções.

Complexidade: M (risco: instabilidade do portal INPI — mitigação: fallback manual).

### 4.6 Patent Landscape via BigQuery

**Novo pacote `landscape/`**:
- `landscape/bigquery_client.py` — `google-cloud-bigquery` (novo dep), autenticação ADC (`gcloud auth application-default login`), **sempre dry-run antes** de executar para estimar bytes; recusa consultas > 10 GB processados sem confirmação.
- `landscape/consultas.py` — consultas parametrizadas prontas (SQL com `UNNEST` para CPC/assignee_harmonized):
  - evolução temporal de depósitos por tecnologia (CPC) e jurisdição
  - top titulares em CPC × país × período
  - mapa de co-classificação (interseções CPC)
  - perfil de um titular: distribuição tecnológica e geográfica
- `landscape/landscape_mcp.py` — servidor MCP `landscape` com 4-5 tools; resultados cacheados em DuckDB (`landscape_cache`, TTL 30 dias).
- Gráficos: dados exportados para seção do dashboard (Chart.js).
- Registrar em `.mcp.json`.
- Testes: mocks do client; validação de SQL por dry-run real opcional (marcado `@pytest.mark.online`).

Complexidade: M. Pré-requisito: Gabriel cria projeto GCP gratuito.

### 4.7 Tarefas Leves (workflow)

- Tabela `tarefas` em `carteira.duckdb`: `id, processo, descricao, prazo_interno, status, criado_em, concluido_em`.
- Tools MCP: `tarefa_criar`, `tarefa_listar`, `tarefa_concluir` (em módulo `inpi/tarefas.py`, ~100 linhas).
- Aparece no dashboard e nos alertas (tarefas vencendo em 7 dias).
- Explicitamente **não** é docketing — sem cálculo de prazo legal, só lembretes internos.

Complexidade: P.

### 4.8 USPTO ODP (destravar)

- Gabriel cria `USPTO_API_KEY` via ID.me; adicionar ao `.env` e ao ambiente do servidor `uspto` em `.mcp.json`.
- Nenhum código novo — 25+ tools já instaladas passam a funcionar.
- Atualizar `docs/capacidades.md` (🔧 → ✅ nas linhas de file wrapper/continuidade/assignments/PTAB).

Complexidade: P (só configuração).

## 5. Refatoração do Código Existente

**Manter intacto**: `anuidades.py`, `jurisdicoes.py`, `escritorios.py`, `familia_epo.py`, `ingest.py`, `carteira.py`, `carteira_manual.py`, `quadro_global.py`, toda a lógica de negócio — funcional e testada. `epo_mcp.py` mantido (melhor arquivo do repo), só ganha cache.

**Refatorar** (Fase 0): `inpi_mcp.py` (god module → 5 módulos), `relatorio_html.py` (camada de dados extraída na 4.3), unificar normalização de acentos (2 implementações → 1 em `inpi/texto.py`).

**Descartar**: `inpi/src|tests|tools` vazios, ~36 arquivos de 0 byte, `lens/` permanece desligado.

## 6. Cronograma de Implementação (ordem de execução para o Sonnet)

| Fase | Conteúdo | Complexidade | Depende de |
|---|---|---|---|
| 0 | Higiene: versionar, limpar, empacotar, modularizar, cache EPO | M | — |
| 1 | Vigilância + anuidades + e-mail + agendamento (4.1, 4.2) | M | 0 |
| 2 | Dashboard evoluído + camada de dados (4.3) | M | 1 |
| 3 | Pipeline anterioridade + OpenAlex (4.4) | M | 0 |
| 4 | PDFs INPI + claim chart BR (4.5) | M | 0 |
| 5 | Landscape BigQuery (4.6) | M | 0 + conta GCP |
| 6 | Tarefas leves (4.7) + ODP (4.8) + docs/capacidades.md atualizado | P | 1 |

Fases 3-5 independentes entre si; ordem acima é a prioridade do stakeholder (monitoramento primeiro).

## 7. Repositórios e Dependências

Novos pacotes pip: `pypdf`, `google-cloud-bigquery`, `pyyaml` (config vigilância). Já instalados: fastmcp, duckdb, httpx, openpyxl, reportlab, python-epo-ops-client (inclui dogpile.cache), pytest.
Nenhum repositório novo a clonar. Ambiente: `.venv` existente; adicionar `pyproject.toml` e `pip install -e .`.
Credenciais novas no `.env`: `USPTO_API_KEY`, `SMTP_USER`, `SMTP_PASS`; ADC do Google via gcloud (fora do .env).

## 8. Plano de Testes

- **Unitários por módulo**: cada módulo novo com `test_*.py` ao lado; fixtures offline (mocks httpx, RPIs sintéticas, PDFs pequenos). Padrão existente mantido.
- **Refatoração Fase 0**: suíte atual (91+ testes) verde após cada corte — critério de não-regressão.
- **Integração**: `@pytest.mark.online` para EPO/BigQuery/OpenAlex reais (rodados manualmente, não no fluxo padrão).
- **End-to-end vigilância**: execução completa de `vigilancia/executar.py` contra base local com watchlist de teste; verificar alertas.md, dashboard e e-mail (modo dry-run sem enviar).
- Comando padrão: `.venv/Scripts/python.exe -m pytest epo inpi vigilancia busca landscape -q`.

## 9. Riscos e Mitigações

| Risco | Mitigação |
|---|---|
| Portal INPI instável p/ PDFs | Fallback: usuário salva PDF manualmente na pasta; parser funciona igual |
| Quota EPO estourada pelos vigias | Cache Dogpile + vigia exterior mensal + `epo_quota` antes de lote |
| BigQuery custo acidental | Dry-run obrigatório + teto de 10 GB por consulta + free tier 1 TB/mês |
| Refatoração quebrar tools MCP | Suíte de testes como contrato; modularização sem mudar assinatura das tools |
| Task Scheduler falhar em silêncio | Log de execução + seção "última execução" no dashboard; ausência de execução > 8 dias vira alerta no próprio agente |
| Despacho anulado gerar ação errada | Vigia 1 com detecção de anulação; regra "pergunte sempre pelo despacho seguinte" mantida na skill |
| LGPD (dados de PF em prospecção) | Manter decisão documentada em `docs/lgpd.md`; alertas por e-mail só com números de processo, sem dados pessoais |

## 10. Instruções para o Sonnet

1. Executar fases na ordem da tabela §6. **Uma fase por sessão/PR**; commit ao final de cada fase com testes verdes.
2. Fase 0 primeiro e completa — nenhuma feature antes de `pip install -e .` funcionando e `pytest` verde sem `sys.path.insert`.
3. Refatoração = comportamento idêntico. Assinaturas das tools MCP não mudam; clientes (conversas salvas, skills) dependem delas.
4. Todo módulo novo em português (nomes, docstrings, mensagens) seguindo o padrão do codebase.
5. Skills: usar `analista-patentes-inpi` como referência de regras anti-alucinação ao escrever docstrings de tools; usar `ui-ux-pro-max` no trabalho de dashboard (obrigatório por CLAUDE.md).
6. Princípios inegociáveis em toda saída nova: âncora tripla, sem veredito, sem número inventado, declarar cobertura, projeção ≠ previsão.
7. Ao final de cada fase: atualizar `docs/capacidades.md` (✅/🔧/❌) e criar evidência de aceite em `docs/aceite/`.
8. Pré-requisitos do Gabriel (fazer quando a fase chegar): chave USPTO ODP (ID.me), projeto GCP + `gcloud auth application-default login`, Gmail app password para SMTP.

## Verificação end-to-end

- Fase 0: `pytest epo inpi -q` verde; `python -c "import inpi.consulta"` sem sys.path; tools MCP respondem no Claude Code (`inpi_processo`, `epo_biblio`).
- Fase 1: rodar `vigilancia/executar.py --dry-run` manualmente; conferir alertas.md e e-mail de teste; tarefa agendada aparece em `Get-ScheduledTask`.
- Fases 3-5: uma busca real ponta a ponta (invenção conhecida → pipeline → relatório com estratégia); um claim chart BR real; uma consulta landscape com dry-run mostrando bytes.
