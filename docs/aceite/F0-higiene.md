# Fase 0 — Higiene e Refatoração

Status: ✅ concluída em 2026-08-05.

Escopo: docs/plano-v2.md §4.0. Repositório tinha ~2.250 linhas de código de produção
fora do git, god module de 1.911 linhas, sem pacote Python (12 `sys.path.insert`
espalhados) e lixo de terminal (~36 arquivos de 0 byte na raiz).

## O que foi feito

1. **Código órfão versionado**: `inpi/carteira.py`, `inpi/panorama_carteira.py`,
   `inpi/relatorio_html.py`, `inpi/test_carteira.py`, `inpi/referencias/` (fontes,
   logos, fonte Inter, Chart.js vendorizado) entraram no git. Trabalho de sessões
   anteriores em `.mcp.json`, `README.md`, `docs/capacidades.md`, `epo/epo_mcp.py`,
   `epo/test_epo_mcp.py`, `inpi/carteira_manual.py`, `inpi/inpi_mcp.py`,
   `inpi/jurisdicoes.py`, `inpi/quadro_global.py`, `inpi/relatorios.py`,
   `inpi/test_inpi_mcp.py` também commitado (estava só no working tree).
2. **Lixo removido**: as ~36 entradas de 0 byte staged para deleção (`0.85`, `DATE`,
   `None`, `dedup`, chaves de fechamento, etc. — resultado de um `>` mal direcionado
   em terminal) foram confirmadas e a deleção commitada. Três arquivos do mesmo
   padrão que ainda não estavam no git (`$c`, `INPADOC`, `SimpleDocTemplate`, também
   0 byte) foram apagados diretamente.
3. **`.gitignore`**: adicionado `.pytest_cache/` e `epo/data/` (cache novo do passo
   6). Não foi adicionado um padrão glob genérico contra o lixo de redirect (tipo
   `[0-9]*` na raiz) — o lixo real veio em formas heterogêneas (números, palavras,
   chaves de fechamento, um Unicode mal decodificado) sem prefixo comum seguro;
   um glob amplo o bastante para pegá-las arriscaria ignorar arquivo legítimo de
   uma letra ou número na raiz. Mitigação é atenção ao redirecionar terminal, como
   o plano já previa.
4. **Diretórios vazios removidos**: `inpi/src/`, `inpi/tests/`, `inpi/tools/`
   (confirmados vazios antes de apagar) e `.claude-flow/` (não referenciado em
   nenhum script ou config do repo, só citado no próprio `docs/plano-v2.md`).
5. **Empacotamento**: `pyproject.toml` na raiz (setuptools, sem dependência nova de
   build) define os pacotes `inpi` e `epo`; `inpi/__init__.py` e `epo/__init__.py`
   criados. `pip install -e .` rodado no `.venv`. Os 12 `sys.path.insert` (mais
   alguns imports bare adicionais descobertos durante a limpeza, dentro de funções e
   de arquivos de teste) foram substituídos por imports absolutos
   (`from inpi import X`, `from epo import epo_mcp`). `inpi/db.py` criado com a
   conexão compartilhada e cacheada ao `inpi.duckdb`; `inpi_mcp.py` e
   `panorama_carteira.py` passaram a importar dali em vez de cada um abrir a sua.
6. **Modularização de `inpi_mcp.py`** (1.911 → 246 linhas): quebrado em
   `inpi/consulta.py` (consulta processual: ficha, busca texto/IPC, despachos,
   titulares — 477 linhas), `inpi/prazos.py` (motor de anuidades/prazos, novidades
   de carteira — 527 linhas) e `inpi/mercado.py` (inteligência de mercado e
   escritórios — 737 linhas). `inpi/mcp_app.py` (12 linhas) guarda a instância
   `FastMCP` compartilhada para quebrar o ciclo de import entre o registro de tools
   e a lógica. `inpi_mcp.py` ficou só com o docstring de negócio, os imports (com
   reexport dos nomes que os testes e `panorama_carteira.py` referenciam como
   atributos do módulo) e as seis tools `carteira_*`, que já eram wrappers finos
   sobre `inpi/carteira.py`. Nenhuma assinatura, nome ou docstring de tool MCP
   mudou — só o arquivo que a contém. `prazos.py` (527) e `mercado.py` (737) ficam
   acima do teto de 500 linhas do CLAUDE.md: são domínios de negócio coesos (o
   próprio plano já os desenhava como um módulo cada) e não havia divisão óbvia sem
   fatiar lógica de negócio, fora de escopo desta fase — sinalizado aqui em vez de
   corrigido às pressas.
7. **Cache EPO ativado**: `epo/epo_mcp.py` já dependia de
   `python-epo-ops-client`, que inclui o middleware `Dogpile` (dogpile.cache) pronto
   — só foi conectado a `epo/data/cache.dbm` com TTL de 2 semanas, no lugar do
   caminho padrão da lib (`/var/tmp/...`). `epo/data/` entrou no `.gitignore`.

## Comandos rodados

```
.venv/Scripts/pip.exe install -e .
.venv/Scripts/python.exe -m pytest epo inpi -q
.venv/Scripts/python.exe -c "import inpi.consulta"
```

## Testes: antes e depois

| Momento | Resultado |
|---|---|
| Baseline (antes de qualquer mudança de código) | 129 passed (457s) |
| Após empacotamento + remoção de `sys.path.insert` | 129 passed |
| Após modularização de `inpi_mcp.py` | 129 passed |
| Após ativar cache EPO | 29 passed (`epo` isolado) |
| Suíte final completa | **129 passed** (170–177s, variação normal) |

`import inpi.consulta` funciona sem `sys.path.insert`, de fora do diretório `inpi/`,
confirmando o empacotamento.

## Commits desta fase

1. `chore: versiona codigo orfao e remove lixo da raiz`
2. `chore: remove diretorios vazios`
3. `refactor: empacota projeto, remove sys.path.insert, unifica conexao duckdb`
4. `refactor: quebra inpi_mcp.py em modulos (consulta, prazos, mercado, db)`
5. `feat: ativa cache dogpile no cliente EPO OPS`
6. `docs: evidencia de aceite Fase 0` (este commit)

## O que ficou pulado ou não foi feito

- Padrão de `.gitignore` contra o lixo de redirect: avaliado e pulado por falta de
  padrão seguro (ver item 3 acima).
- `docs/capacidades.md` não tem seção de status de arquitetura/empacotamento; não foi
  criada uma nova seção para isso, por não ser obrigatório e o documento ser focado
  em capacidades de resposta, não em arquitetura interna.
- `prazos.py` e `mercado.py` acima de 500 linhas (ver item 6).

## Próximo passo (fora de escopo aqui)

Fase 1 do plano (`docs/plano-v2.md` §4.1): pacote `vigilancia/` — reingestão,
5 vigias (watchlist de carteira, concorrentes, IPCs, anuidades, status legal
exterior), orquestração, e-mail e agendamento via Task Scheduler. Depende desta
Fase 0 estar fechada, o que agora está.
