# Evidência de aceite — Fase 5: Patent Landscape via BigQuery (plano-v2 4.6)

## Escopo entregue

- `landscape/bigquery_client.py`: cliente BigQuery via ADC (`google.cloud.bigquery.Client`).
  Dry-run obrigatório antes de qualquer execução real (`estimar_bytes`); recusa
  consultas estimadas acima de 10 GB processados (`ConsultaMuitoGrandeError`),
  a menos que o chamador passe `confirmar_acima_10gb=True`.
- `landscape/consultas.py`: 4 consultas parametrizadas contra
  `patents-public-data.patents.publications` (166M publicações, `UNNEST` de
  `cpc` e `assignee_harmonized`), sempre com `bigquery.ScalarQueryParameter`
  (nunca concatenação de string do valor do usuário no SQL):
  - `evolucao_temporal` — depósitos por ano/CPC/jurisdição
  - `top_titulares` — ranking de titulares por CPC × país × período
  - `co_classificacao` — pares de códigos CPC que mais coocorrem
  - `perfil_titular` — distribuição tecnológica e geográfica de um titular
- `landscape/cache.py`: cache local em DuckDB (`landscape/data/landscape_cache.duckdb`),
  chave = hash da consulta + argumentos, TTL 30 dias.
- `landscape/landscape_mcp.py`: servidor MCP `landscape`, 4 tools (uma por
  consulta), cache-first (só bate no BigQuery se não houver cache válido).
  Registrado em `.mcp.json`.
- `landscape/dashboard.py` + `inpi/painel_dados.py::_landscape()` +
  `inpi/relatorio_html.py::_secao_landscape()`: a seção "Landscape" do
  dashboard lê **só do cache local** (nunca dispara consulta ao BigQuery na
  hora de renderizar). Sem cache, cai no placeholder de sempre — fallback
  gracioso, dashboard nunca quebra por falta de landscape.

## Comandos

```
.venv/Scripts/python.exe -m pip install -e .
.venv/Scripts/python.exe -m pytest epo inpi vigilancia busca -q      # antes: 167 passed
.venv/Scripts/python.exe -m pytest epo inpi vigilancia busca landscape -q   # depois
```

## Testes

- `landscape/test_bigquery_client.py`: dry-run chamado antes de executar; teto de
  10 GB recusa sem confirmação e aceita com `confirmar_acima_10gb=True`; teto
  customizável.
- `landscape/test_consultas.py`: valor malicioso do usuário nunca aparece na
  string SQL final (vai por `ScalarQueryParameter`); conversão de data
  `AAAA-MM-DD` → `INT64 AAAAMMDD`; fonte declarada em todo retorno.
- `landscape/test_cache.py`: grava/lê, distingue por argumento, expira após TTL.
- `landscape/test_landscape_mcp.py`: cache-first (não bate no BigQuery quando
  há cache), salva no cache quando bate, erro de credencial (ADC ausente)
  vira `RuntimeError` com instrução clara (`gcloud auth application-default login`).
- `inpi/test_painel_dados.py` (já existente, sem alteração): dashboard sem
  cache de landscape continua caindo no placeholder "Fase 5" — não regrediu.
- Nenhum teste bate em rede real ou BigQuery real nesta sessão. Não existe
  `@pytest.mark.online` neste pacote ainda — não havia nada testável de
  verdade sem ADC configurado (dry-run real também exige credencial). Marker
  `online` foi registrado em `pyproject.toml` (`[tool.pytest.ini_options]`,
  `addopts = -m "not online"`) para uso quando alguém adicionar esse teste
  depois que o Gabriel configurar o gcloud.

## Commits

1. `feat(landscape): cliente BigQuery com dry-run obrigatorio e teto de 10GB`
2. `feat(landscape): consultas parametrizadas e servidor MCP landscape`
3. `feat(dashboard): conecta secao de graficos landscape com fallback gracioso`
4. `docs: evidencia de aceite Fase 5` (este arquivo)

## Validação ponta a ponta (pós-sessão inicial)

`gcloud` CLI instalado via winget, `gcloud auth application-default login`
rodado contra o projeto GCP `patentes-landscape`. Consulta real executada:

```
consultas.evolucao_temporal(cliente(), cpc_prefix='A61K', pais='BR',
                             desde='2018-01-01', ate='2022-12-31',
                             confirmar_acima_10gb=True)
```

Dry-run funcionou como projetado: estimou 16.48 GB, acima do teto de 10 GB,
recusou sem `confirmar_acima_10gb=True` (`ConsultaMuitoGrandeError`), e
executou de verdade com a flag. Retornou depósitos reais de A61K no Brasil
por ano (2018–2022), com `fonte` e parâmetros no payload — âncora tripla
confirmada. `docs/capacidades.md` deve ser atualizado (🔧 → ✅ na linha de
landscape) na próxima passada de documentação.
