# Evidencia de aceite -- Fase 3 (Pipeline de Busca de Anterioridade)

Escopo: docs/plano-v2.md secao 4.4 / cronograma secao 6 (Fase 3).

## Baseline

```
.venv/Scripts/python.exe -m pytest epo inpi vigilancia -q
145 passed in 220.90s
```

## O que foi implementado

- `busca/pipeline.py` -- `busca_anterioridade(conceitos, ipc=None, desde=None,
  data_critica=None, limite_por_fonte=20)`: roda INPI (texto via `inpi_busca_texto`,
  IPC via `inpi_busca_ipc`) e EPO OPS (CQL via `epo_busca`/`epo_biblio`) em
  paralelo com `concurrent.futures.ThreadPoolExecutor` (stdlib, sem dependencia
  nova). Deduplica documentos de patente que pertencem a mesma familia INPADOC,
  reusando `inpi/familia_epo.py` (para resultados do INPI) e `epo_familia_inpadoc`
  (para resultados do EPO) -- nenhuma logica de familia foi reimplementada.
  Devolve `estrategia.fontes_executadas` com hits por fonte e o que falhou, e
  nunca emite veredito de patenteabilidade.
- `busca/openalex.py` -- cliente httpx para `api.openalex.org/works`, sem chave,
  com cache em disco (json por hash de consulta, TTL 30 dias -- mesmo padrao de
  `inpi/familia_epo.py`).
- `busca/busca_mcp.py` -- servidor MCP `busca`, registrado em `.mcp.json`, com as
  tools `busca_anterioridade` e `busca_npl` (OpenAlex isolado).
- Testes: `busca/test_pipeline.py` (dedup por familia sintetica, fonte com erro
  nao derruba o pipeline, `data_critica` so marca fato objetivo de data) e
  `busca/test_openalex.py` (mocks httpx, cache, erro de rede). Nenhum teste bate
  em rede real.

## O que ficou de fora (documentado no proprio pipeline)

- **PPUBS (USPTO/BRS)**: nao ha cliente Python direto e reusavel neste repo, so o
  servidor MCP `uspto` (`ppubs_search_patents`). Fica como TODO explicito em
  `busca/pipeline.py` (`cobertura["ppubs"]`) -- fora de escopo reimplementar um
  cliente PPUBS do zero nesta fase.
- Decomposicao semantica de conceitos/sinonimos: deliberadamente NAO esta no
  Python -- e trabalho da skill `analista-patentes-inpi`, chamada antes de
  `busca_anterioridade`.

## Testes depois

```
.venv/Scripts/python.exe -m pytest busca -q
8 passed in 1.37s

.venv/Scripts/python.exe -m pytest epo inpi vigilancia busca -q
161 passed in 178.44s (0:02:58)
```

(161 = 145 do baseline + 8 novos de `busca/` + 8 que a Fase 4, em andamento em
paralelo no mesmo repo, ja tinha adicionado em `inpi/pdf_inpi.py`.)

## Commits

1. `feat(busca): pipeline de anterioridade, dedup por familia INPADOC` -- inclui
   `busca/pipeline.py`, `busca/busca_mcp.py`, `busca/openalex.py`, testes e o
   registro em `.mcp.json` (empacotados juntos: a tool `busca_npl` depende do
   mesmo servidor MCP criado para `busca_anterioridade`).
2. `docs: evidencia de aceite Fase 3` -- este arquivo.
