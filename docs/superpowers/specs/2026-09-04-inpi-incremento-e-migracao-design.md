# Incremento sem re-varrer tudo, migração de fonte pra plataforma nova, e benchmark de mercado

## Contexto

`docs/pesquisa/inpi_plataforma_nova.md` e o spec anterior
(`2026-09-04-inpi-plataforma-nova-design.md`) já validaram e implementaram
`inpi/coleta_plataforma_nova.py`: a plataforma nova do INPI
(`servicos.patentes.inpi.gov.br`) como fonte primária de CPC+anuidades,
headless, com fallback automático pro pePI (`coletar_com_fallback_pepi()`).
O que falta é decidir **como disparar essa coleta** — hoje ela roda sobre
uma lista passada manualmente, não integrada ao ciclo semanal de ingestão —
e fechar duas pendências que o spec anterior deixou em aberto: se "Eventos
de Pedido" equivale a petições, e o que fazer com o Portal de Estatísticas
já carregado (`estatistica_nacional`).

## Seção 1 — Arquitetura de incremento

Hoje a coleta roda sobre a carteira inteira toda vez que é acionada. O
objetivo é rodar só sobre o que mudou.

**Fluxo semanal (integrado à reingestão):**

1. `vigilancia/reingestao.py` já preserva `inpi_anterior.duckdb` antes do
   `ingest.main()` recriar o banco — nenhuma mudança aqui.
2. Novo passo, após a reingestão: computa o `_add` do `EXCEPT` que
   `vigilancia/sync_motherduck.py::_diff_tabela` já calcula pra tabela
   `despachos` (mesma lógica — linha inteira, não por chave — reusada, não
   duplicada), extrai `DISTINCT numero_inpi` dessas linhas novas. Essa é a
   lista de prioridade da semana: processos com despacho novo no dump.
3. `inpi/coleta_plataforma_nova.py::coletar_com_fallback_pepi()` roda **só
   sobre essa lista** — não a carteira inteira. Plataforma nova primária,
   pePI no resíduo "não encontrado" (comportamento já implementado, só muda
   a origem de `numeros_inpi`).
4. Grava no mesmo `ficha-extras.csv` via `registrar()` — schema inalterado,
   `inpi/ingest.py` continua reconstruindo `ficha_extras`/`ficha_peticoes`/
   `ficha_anuidades` do zero a partir do CSV acumulado.

**Rede de segurança — watermark por `coletado_em`:** job separado, cadência
mais lenta que a semanal (ex. mensal), seleciona `numero_inpi` cujo
`ficha_extras.coletado_em` tem mais de 60 dias (ou nunca foi coletado) e
roda o mesmo `coletar_com_fallback_pepi()` sobre esse resíduo. Cobre o caso
de mudança sem despacho correspondente no dump daquela semana (ex. GRU de
anuidade processada com atraso).

**Por que a rede de segurança é necessária, não opcional — achado da
validação ao vivo (2026-09-04):** tentou-se validar empiricamente se
despacho-novo correlaciona com mudança real na plataforma nova, comparando
um grupo de 25 processos com despacho nos últimos 30 dias contra um grupo
de 25 sem despacho nos últimos 180 dias, ambos contra o baseline armazenado
em `ficha_extras`/`ficha_anuidades`. **Resultado inconclusivo por
confundimento, não por ausência de sinal:** os dois grupos deram 100% de
"mudou algo" — mas o baseline (`ficha_extras.coletado_em` entre
2026-08-11 e 2026-08-24, herdado do pePI) mistura diferença **temporal**
(11-24 dias de defasagem) com diferença de **cobertura entre fontes**: a
plataforma nova, sem filtro (`customQuery: []`), devolve o histórico
completo de anuidades, enquanto o pePI capturava um recorte parcial — por
isso `n_anu_novo > n_anu_antigo` sistematicamente nos dois grupos,
independente de despacho. Medir a correlação de verdade exige dois
snapshots da própria plataforma nova (semana N vs. N+1), que só existirão
depois de algumas rodadas do fluxo acima — o log semana-a-semana vira o
dado pra validar ou ajustar a heurística depois, sem bloquear a
implementação agora.

## Seção 2 — Migração de fonte e live-vs-batch

**Fonte primária por tipo de dado:**

| Dado | Fonte primária | Fallback | Status |
|---|---|---|---|
| CPC + anuidades | Plataforma nova | pePI (resíduo "não encontrado") | Implementado, falta disparo incremental (Seção 1) |
| Petições/serviços (GRU) | pePI | — | Sem mudança — não existe endpoint equivalente na plataforma nova |
| Despachos | Dump aberto (`despachos.csv`) | — | Sem mudança |

**"Eventos de Pedido" descartado como fonte** — confirmado ao vivo
(2026-09-04): `getListingData(tipo="eventos")` devolve despacho publicado na
RPI (código RPI, data, código de despacho tipo "8.6"/"8.11", texto legal
citando Art. 86/87 da LPI, títulos como "Manutenção do Arquivamento") — não
tem banco/GRU/protocolo/valor, a assinatura de petição protocolada em
`ficha_peticoes`. É o mesmo conceito de `despachos.csv`, que o dump aberto
já cobre; a plataforma nova não adiciona nada aqui. `_COMPONENT_ID_EVENTOS`
em `inpi/plataforma_nova.py` fica no código (endpoint mapeado, pode ser
útil futuramente) mas não vira pipeline de dado.

**Live vs. batch:** nenhuma tool MCP chama a plataforma nova ao vivo. Toda
coleta é batch, disparada pelo cron da Seção 1 (semanal) + rede de
segurança (mensal). Único ponto de chamada de rede externa é o job de
coleta — mesmo padrão que o projeto já usa pro pePI+Tor hoje. Tools MCP
(`inpi_processo` etc.) continuam lendo só do DuckDB local/MotherDuck.

## Seção 3 — Benchmark carteira-vs-mercado

Nova tool `inpi_benchmark_mercado(escritorio_canonico, ano_inicial=None,
ano_final=None, campo_tecnologico=None)`, construída sobre
`estatistica_nacional` (já carregada, `inpi/estatistica_nacional.py`) e a
carteira do escritório (mesmo padrão de `inpi_mercado`):

1. **Taxa de concessão comparada** — % concessão/indeferimento/arquivamento
   da carteira do escritório vs. média nacional, mesmo `campo_tecnologico`/
   intervalo de ano.
2. **Share de mercado** — % que a carteira representa do volume nacional de
   depósitos naquele campo tecnológico.
3. **Série temporal comparada** — taxa de crescimento ano-a-ano da carteira
   vs. nacional/setorial, mesma faixa de anos.

**Dependência nova, fora do que já existe:** `estatistica_nacional` agrupa
por `campo_tecnologico` (taxonomia WIPO, ~35 campos tecnológicos), mas a
carteira só carrega código IPC (`inpi/mercado.py` e afins) — **não existe
hoje nenhum mapeamento IPC→campo_tecnologico no projeto**. Sem ele, dá pra
comparar por `ano`/`decisao`/`tipo_ativo` (sem quebra por campo), mas não
cruzar por área tecnológica, que é o comparativo mais informativo.
Escopo inclui embutir a tabela de concordância pública IPC↔WIPO-35-campos
como CSV de referência (mesmo padrão de `procuradores-sigilo.csv` —
`inpi/referencias/`), carregada por `inpi/ingest.py` como tabela auxiliar
(`ipc_campo_tecnologico` ou nome equivalente), sem precisar raspar nada —
é dado público e estático (classificação Schmoch/WIPO, a mesma que o
Portal de Estatísticas do INPI usa).

## Seção 4 — Superfície Copilot M365

Sem mudança arquitetural: qualquer tool nova (`inpi_benchmark_mercado`) ou
recém-exposta (`inpi_estatistica_nacional`, hoje só local, não está em
`remoto/servidor_mcp.py`) segue o runbook já documentado em
`docs/agente-copilot.md` — refresh manual no Copilot Studio pós-deploy.
Decisão de incluir cada tool no `servidor_mcp.py` (Caso A: refresh do
conector inteiro reimporta todas de uma vez) fica pro plano de
implementação, não é decisão de arquitetura.

## Fora de escopo

- Medir throughput em paralelismo/rajada maior da plataforma nova antes de
  escalar o volume do fluxo semanal (pendência já registrada no spec
  anterior, não repetida aqui).
- Investigar os ~21% de "não encontrado" no formato legado (`PIxxxxxxx`) —
  cai no fallback pePI de qualquer forma, não bloqueia esta arquitetura.
- Qualquer uso de `_COMPONENT_ID_EVENTOS`/"Eventos de Pedido" como fonte de
  dado — descartado (Seção 2), fica só documentado no código.

## Verificação

- Seção 1: depois de 3-4 semanas rodando o fluxo incremental, comparar o
  volume de `numero_inpi` reprocessados pela lista de prioridade (despacho
  novo) vs. pela rede de segurança (watermark) — se a rede de segurança
  estiver pegando uma fração grande de mudanças reais que o despacho não
  sinalizou, a heurística de prioridade precisa de ajuste (documentar como
  achado, não travar a decisão agora).
- Seção 2: `ficha_peticoes` continua vindo só do pePI — sem regressão de
  cobertura (comparar contagem de linhas antes/depois da migração).
- Seção 3: `inpi_benchmark_mercado` bate contra um caso de controle manual
  (ex. um escritório conhecido, campo tecnológico com poucos processos,
  conferir a mão contra a UI do Portal de Estatísticas).
