# Evidência de aceite — Fases 0 a 5: correções de base e métricas de negócio (plano-v2)

## Escopo entregue

### Fase 0 — Base
- `pyproject.toml`: dependências completas (`mcp`, `duckdb`, `python-dotenv`,
  `dogpile.cache`, `python-epo-ops-client`, `httpx`, `requests`, `openpyxl`,
  além das 3 já declaradas) — `pip install -e .` agora reconstrói o ambiente.
- `landscape/landscape_mcp.py`: as 4 tools aceitam `confirmar_acima_10gb`
  (o cliente BigQuery já suportava; faltava o plumbing). Fica **fora da chave
  de cache** — não muda o conteúdo do resultado, só se a consulta roda.
- `landscape/cache.py` + `landscape/dashboard.py`: coluna `nome_consulta`
  (migração idempotente `ADD COLUMN`); dashboard mostra o mais recente **por
  tipo** de consulta, não "o último qualquer".
- `lens/` removido (órfão, não registrado em `.mcp.json`).

### Fase 1 — Gargalos INPI (`inpi/gargalos.py`)
- `inpi_tempo_fases`, `inpi_backlog`, `inpi_pipeline_comparado`.
- Marco de depósito usa `biblio.data_deposito`, **não** o despacho `1.1`:
  validado empiricamente que só 47 de 987 mil processos têm `1.1` e `3.1`
  presentes ao mesmo tempo — a hipótese original do plano (join pelos dois
  despachos) não se sustentava. Publicação/parecer/concessão/indeferimento
  usam despacho `3.1`/`6.1`+`7.1`/`9.1`/`9.2`, já documentados em
  `inpi/anuidades.py` e `inpi/referencias/prazos-observados.md`.

### Fase 2 — Financeiro previsivo (`inpi/financeiro.py`)
- `financeiro_projecao` reusa `quadro_global.montar` (BR + exterior) e agrega
  por mês × jurisdição — **sem R$**, só contagem, até o escritório fornecer
  `custos.yaml`.
- `financeiro_janelas_desistencia` lista pedidos em trâmite (não concedidos,
  não encerrados) com anuidade em débito ou complementação devida.
- Corrigido bug pré-existente em `inpi/quadro_global.py::montar`: import
  `from familia_epo import familia` sem o prefixo `inpi.`, quebrando toda
  chamada da função.

### Fase 3 — Saúde de portfolio (`inpi/saude.py`)
- `carteira_saude`: score 0-100 (vigência 40 + qualidade dos dados 30 +
  cobertura geográfica 15 + idade do portfólio 15), sem tocar rede — só lê
  `carteira.duckdb` já povoada. `lacunas` sempre acompanha o número.

### Fase 4 — Ponte carteira × landscape (`landscape/carteira_bridge.py`)
- `cpcs_da_carteira`: prefixo IPC (≈ CPC até a subclasse, 4 caracteres) mais
  frequente na carteira BR de um cliente.
- `landscape_carteira`: cruza isso com `top_titulares`/`evolucao_temporal`
  do BigQuery (via `landscape/mcp_app.py::_rodar`, cache-first).
- Extraído `landscape/mcp_app.py` (mesma instância `mcp` + helper `_rodar`)
  para quebrar ciclo de import entre `landscape_mcp.py` e `carteira_bridge.py`
  — mesmo padrão de `inpi/mcp_app.py`.

### Fase 5 — Radar de prospecção (`inpi/radar.py`)
- `inpi_radar`: versão incremental de `inpi_prospeccao`, com marca-d'água de
  `numero_rpi` por `(escritorio, ipc, uf)` persistida em `carteira.duckdb`.
  Marco de "pedido novo" = despacho `3.1` (publicação), não o depósito.
  `criar_tarefas=True` grava uma tarefa (`inpi_tarefas`) por titular achado.

## Comandos

```
.venv/Scripts/python.exe -m pip install -e .
.venv/Scripts/python.exe -m pytest -q --ignore=vendor
```

## Testes

- `inpi/test_gargalos.py`: estatística pura (`_estatisticas_dias`) + smoke
  test contra a base real do INPI (mediana coerente, filtro sem resultado
  falha alto, comparativo escritório vs. média).
- `inpi/test_financeiro.py`: janelas de desistência contra a base real
  (titular válido, com candidatos, inexistente); projeção agregada marcada
  `online` (chama família INPADOC via EPO).
- `inpi/test_saude.py`: carteira populada em banco temporário via
  `descobrir_inpi` (leitura pura, sem rede); score soma os 4 componentes,
  nunca excede o teto, carteira vazia é erro (não zero).
- `landscape/test_carteira_bridge.py`: bancos sintéticos + `_rodar` mockado,
  sem rede/BigQuery.
- `landscape/test_landscape_mcp.py`: ajustado para os mocks apontarem para
  `landscape/mcp_app.py` após a extração do módulo.
- `inpi/test_radar.py`: watermark contra a base real — primeira rodada traz
  histórico e avança a marca-d'água; segunda rodada sem novidade é vazia;
  `criar_tarefas` grava uma por titular; radares de IPC diferente têm
  watermark independente.
- Confirmado end-to-end contra o BigQuery real (`landscape_carteira` com
  `top_cpc=1` na carteira da Aptar): o teto de 10GB recusou a consulta
  corretamente (`ConsultaMuitoGrandeError`, 18.22 GB estimados) — não forçado
  com `confirmar_acima_10gb=True` para não gastar quota.

## Commits

1. `feat(fase0): completa deps, expoe teto de 10GB no landscape, dashboard por tipo`
2. `feat(gargalos): tempo por fase, backlog e comparativo de pipeline INPI`
3. `feat(financeiro,saude): projecao de anuidades, desistencia e score de carteira`
4. `feat(landscape,radar): ponte carteira-landscape e radar incremental de prospeccao`
