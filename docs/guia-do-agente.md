# Guia do Agente de Patentes

O que este projeto é, o que ele responde, como usar, onde funciona.

---

## 1. O que é

Assistente de IA para escritório de gestão de PI, rodando dentro do Claude Code
via MCP (Model Context Protocol), com uma camada de scripts Python agendados
que rodam sem LLM (vigilância, reingestão, dashboard).

**Missão**: organizar e vigiar informação pública de PI — busca, prazos,
inteligência competitiva, landscape. **Não é** o docketing do escritório, não
redige patentes/pareceres, não dá veredito de patenteabilidade. Regra de ouro:
*o agente informa e confere; o controle é do procurador*.

Detalhes de arquitetura e decisões: `docs/plano-v2.md`. Levantamento fonte a
fonte do que responde e do que não responde: `docs/capacidades.md` (mais
granular que este guia, vale ler se a pergunta for específica).

---

## 2. Onde funciona

- **Local, Windows, dentro deste repositório** (`C:\Users\Gabriel\Desktop\Patentes`).
  Python 3.12 num `.venv` já instalado (`pip install -e .`).
- **Interface**: Claude Code, via 5 servidores MCP configurados em `.mcp.json`
  (`inpi`, `epo`, `uspto`, `busca`, `landscape`). Cada um é um processo Python
  separado que expõe "tools" que o Claude chama durante a conversa.
- **Camada autônoma**: `vigilancia/executar.py`, roda sem LLM, agendada no
  Windows Task Scheduler (domingo 08h, após o refresh de sábado dos dados
  abertos). Gera `alertas.md`, atualiza o
  dashboard HTML e manda e-mail de resumo (quando `SMTP_USER`/`SMTP_PASS`
  estiverem configurados no `.env`).
- **Dados**: DuckDB local (`inpi/data/*.duckdb`, `vigilancia/data/*.duckdb`,
  `landscape/data/*.duckdb`) — nada roda em nuvem exceto as chamadas às APIs
  externas (EPO, USPTO, BigQuery, OpenAlex).

---

## 3. Posso usar fora do Claude Code?

**Sim, com ressalvas:**

- **Como servidor MCP em outro cliente**: qualquer cliente compatível com MCP
  (não só Claude Code) pode apontar para os mesmos processos
  (`.venv\Scripts\python.exe inpi\inpi_mcp.py`, etc.) — é o protocolo padrão,
  não há acoplamento ao Claude Code especificamente.
- **Como biblioteca Python direto**: o projeto é um pacote instalável
  (`pyproject.toml`, `pip install -e .`). Dá para importar e chamar as funções
  sem MCP nenhum, ex.:
  ```python
  from inpi.consulta import inpi_processo
  inpi_processo("BR 10 2022 010731 2")
  ```
  As tools MCP são só um wrapper fino em cima dessas funções.
- **Sem Claude/LLM nenhum**: os scripts autônomos (`vigilancia/executar.py`,
  `inpi/relatorio_html.py`, `landscape/consultas.py`) rodam puros, via linha
  de comando, sem precisar de nenhum modelo de IA — são Python + DuckDB +
  chamadas HTTP para as fontes públicas.
- **O que exige Claude Code (ou outro LLM) de fato**: só a etapa de
  decomposição de conceitos do pipeline de busca de anterioridade
  (`busca_anterioridade` recebe conceitos já decompostos — quem decompõe a
  descrição livre da invenção em conceitos/sinônimos é o LLM via skill
  `analista-patentes-inpi`, não o código) e a leitura interpretativa de
  resultados em geral (claim charts, pareceres). O código nunca dá veredito
  de patenteabilidade sozinho nem com LLM.
- **Replicável por qualquer pessoa**: sem integração paga, single-user, cada
  usuário usa suas próprias credenciais (`.env`).

---

## 4. Fontes de dados e o que cada uma cobre

| Fonte | Cobertura | Credencial | Status |
|---|---|---|---|
| INPI Dados Abertos | Brasil — 5,3M despachos, base de verdade nacional | nenhuma | ✅ ligado |
| EPO OPS v3.2 | Famílias INPADOC, status legal mundial (100+ países), texto EP/WO | `EPO_OPS_KEY`/`EPO_OPS_SECRET` (grátis, 4GB/sem) | ✅ ligado, com cache |
| USPTO PPUBS | Full-text de patentes US | nenhuma | ✅ ligado |
| USPTO ODP + PTAB | File wrapper, continuidade, assignments, litígios US | `USPTO_API_KEY` (ID.me) | 🔧 **desligado por decisão** — ver §7 |
| Google Patents (BigQuery) | Landscape macro, 166M publicações mundiais | ADC (`gcloud auth`) | ✅ ligado, validado |
| OpenAlex | Literatura científica (NPL) | nenhuma | ✅ ligado, com cache |
| PDFs INPI | Reivindicações de pedidos BR publicados | nenhuma (download best-effort + fallback manual) | ✅ ligado |

---

## 5. O que ele faz — exemplos por área

Pergunte em linguagem natural na conversa do Claude Code; ele decide qual tool
chamar. Exemplos reais de pergunta → o que acontece:

### Consulta de processo (Brasil)

- *"Qual o andamento do BR 10 2022 010731 2?"* → `inpi_processo`: título,
  resumo, IPC, titular, inventores, histórico completo de despachos.
- *"Esse pedido teve transferência de titularidade?"* → despacho `25.1` no
  histórico.
- *"É entrada de fase nacional de um PCT? Qual o WO?"* → `numero_pct`,
  `numero_wo` na ficha.
- *"Esse despacho foi anulado depois?"* → **pergunte sempre** — o INPI
  retifica (caso real documentado: `PI0803071`, anuidade notificada e anulada
  7 dias depois).

### Busca

- *"Existe patente BR sobre embalagem biodegradável de alginato?"* →
  `inpi_busca_texto` (título/resumo).
- *"Busca por classificação, IPC B65D 65/46"* → `inpi_busca_ipc`.
- *"Busca de anterioridade completa: minha invenção é X, cruza INPI + EPO +
  literatura científica"* → `busca_anterioridade` + `busca_npl` (pipeline
  paralelo, dedup por família INPADOC, estratégia de busca auditável — nunca
  dá veredito, só organiza o que existe).
- *"Quais as reivindicações desse pedido BR publicado?"* →
  `inpi_reivindicacoes` (baixa/lê o PDF, extrai e estrutura por seção).

### Prazos e anuidades

- *"Quando vence a próxima anuidade desse caso?"* → `inpi_anuidades` — cálculo
  determinístico art. 84, sempre com data-base, regra aplicada e despacho
  `16.1` como prova.
- *"Anote um lembrete interno nesse processo, não é prazo legal"* →
  `tarefa_criar`/`tarefa_listar`/`tarefa_concluir` (explicitamente **não** é
  docketing — sem cálculo de prazo legal).
- *"Tem alerta pendente na minha carteira vigiada?"* → `inpi_alertas` (vindo
  da vigilância semanal autônoma: despacho novo, anulação, anuidade entrando
  na janela de 90 dias).

### Exterior / família de patentes

- *"Esse pedido BR tem equivalente em outros países?"* →
  `epo_familia_inpadoc`.
- *"A patente US caducou por falta de taxa de manutenção?"* →
  `epo_status_legal` (eventos `LAPS`/`FPAY`/`REMI`).
- *"Esse EP foi validado em quais países, mesmo os do Acordo de Londres (sem
  publicação nacional)?"* → status legal INPADOC (`PGFP`), cobre os 9 países
  de Londres que a busca de família sozinha não vê.
- *"Quais reivindicações desse EP/WO?"* → `epo_texto_integral`.

### Inteligência de mercado e concorrência

- *"Que pedidos meu concorrente depositou nos últimos 5 anos?"* →
  `inpi_portfolio_titular`.
- *"Meu concorrente teve pedido arquivado ou indeferido recentemente?"* →
  varredura por titular + código de despacho.
- *"Quem são os maiores depositantes numa IPC?"* → `inpi_mercado`.
- *"Quais escritórios de PI concorrem comigo, e como evoluiu a carteira deles
  no tempo?"* → `inpi_prospeccao`, `inpi_serie_mercado`,
  `inpi_movimentacao_escritorio`.

### Landscape (visão macro, BigQuery)

- *"Como evoluiu o depósito em CPC A61K no Brasil, últimos 5 anos?"* →
  `landscape_evolucao_temporal` (validado com dado real: 4.036→1.584
  depósitos/ano 2018-2022).
- *"Quem são os maiores titulares numa tecnologia, por país e período?"* →
  `landscape_top_titulares`.
- *"Quais tecnologias mais coocorrem nessa classificação?"* →
  `landscape_co_classificacao`.
- *"Perfil tecnológico e geográfico completo de um titular"* →
  `landscape_perfil_titular`.
- Toda consulta faz **dry-run obrigatório** antes de rodar — recusa
  automaticamente acima de 10GB processados a menos que você confirme
  explicitamente (protege contra custo acidental; free tier é 1TB/mês).

### Dashboard e vigilância

- Rodar `vigilancia/executar.py` (manual ou via Task Scheduler) faz: baixa
  CSVs novos do INPI → roda 5 vigias (watchlist da carteira, concorrentes,
  IPCs vigiadas, anuidades entrando na janela de 90 dias, status legal
  exterior mensal) → grava alertas → regenera o dashboard HTML
  (`docs/relatorios/panorama_clarke_modet.html`, abre no navegador, sem
  servidor) → manda e-mail de resumo.
- `--dry-run` faz tudo, menos mandar o e-mail de verdade.

### Carteira do escritório (ClarkeModet)

- `carteira_ingerir`, `carteira_listar`, `carteira_panorama`,
  `carteira_validacoes_ep`, `carteira_jurisdicoes_a_revisar` — gestão da
  carteira de clientes já ingerida, cruzando com todas as fontes acima.

---

## 6. O que ele explicitamente não faz

- Não dá veredito de patenteabilidade ("está antecipado" / "não é
  patenteável") — só organiza informação para o examinador/procurador decidir.
- Não é docketing: não calcula prazo legal de exigência, não é fonte de
  verdade sobre prazo processual vencendo.
- Não sabe se uma anuidade foi de fato **paga** — as bases mostram
  notificação, não quitação.
- Não inventa número: se a fonte não cobre, a resposta é "não sei" ou "fora de
  escopo", nunca um valor estimado apresentado como fato.
- Detalhe completo, pergunta por pergunta: `docs/capacidades.md`.

---

## 7. Pendências / configuração do usuário

| Item | Status | O que falta |
|---|---|---|
| INPI, EPO, PPUBS, OpenAlex, BigQuery landscape | ✅ funcionando | nada |
| `gcloud` ADC (landscape) | ✅ configurado e validado com consulta real | nada |
| USPTO ODP + PTAB (file wrapper, continuidade, assignments, IPR/PGR) | 🔧 **fora por decisão do usuário** | chave via `account.uspto.gov` exige ID.me com passaporte não-americano + chamada de vídeo — não concluído; sem chave, as tools do servidor `uspto` (`odp_*`, `ptab_*`) não respondem |
| E-mail de alerta semanal | 🔧 código pronto, sem credencial real testada | `SMTP_USER`/`SMTP_PASS` (senha de app do Gmail) no `.env` |
| Agendamento automático | 🔧 script pronto (`scripts/instalar_agendamento.ps1`), não confirmado se já foi rodado | rodar o `.ps1` como admin e conferir `Get-ScheduledTask` |

Toda credencial vai em `.env` (nunca commitado — veja `.env.example` para os
nomes exatos das variáveis).

---

## 8. Evidência e auditoria

Cada fase de implementação tem um documento de aceite em `docs/aceite/`
(`F0-higiene.md` até `F6-tarefas.md`) com comandos rodados, resultado de
testes antes/depois e commits. 183 testes automatizados cobrem o
comportamento (`pytest epo inpi vigilancia busca landscape -q`).
