# Evidência de aceite — Fase 6 (Tarefas Leves)

Ref.: `docs/plano-v2.md` seção 4.7, tabela §6 linha "Fase 6".

## Baseline (antes)

```
.venv/Scripts/python.exe -m pytest epo inpi vigilancia busca -q
161 passed in 228.44s (0:03:48)
```

## Comandos rodados

```
.venv/Scripts/python.exe -m pytest inpi/test_tarefas.py inpi/test_painel_dados.py inpi/test_inpi_mcp.py -q
89 passed in 174.76s (0:02:54)

.venv/Scripts/python.exe -m pytest epo inpi vigilancia busca -q
167 passed in 201.65s (0:03:21)
```

Sem regressão nos 161 testes anteriores; 6 testes novos em `inpi/test_tarefas.py`
(criar/listar/concluir, filtro por processo, recorte de vencimento em 7 dias, banco
inexistente) e 1 teste novo em `inpi/test_painel_dados.py` (dashboard conecta tarefas
abertas + alerta de vencimento com dados sintéticos).

## Commits

1. `feat(inpi): tabela e tools de tarefas leves (criar/listar/concluir)`
2. `feat(dashboard): conecta secao de tarefas abertas e alerta de vencimento`
3. `docs: evidencia de aceite Fase 6-tarefas` (este arquivo)

## O que foi entregue

- `inpi/tarefas.py` (~120 linhas) — tabela `tarefas` em `carteira.duckdb` (mesmo banco de
  `inpi/carteira.py`, tabela própria; reusa o padrão `con(read_only=...)` já existente lá,
  não `inpi/db.py`, que é a conexão somente-leitura de `inpi.duckdb`). Colunas: `id,
  processo, descricao, prazo_interno, status, criado_em, concluido_em`. Quatro funções:
  `tarefa_criar`, `tarefa_listar`, `tarefa_concluir`, `tarefas_vencendo` (recorte usado pelo
  dashboard). Toda saída traz `origem = "lembrete interno, não é prazo legal (não é
  docketing)"` — não reusa `inpi/prazos.py`, `prazo_interno` é campo de data livre.
- `inpi/inpi_mcp.py` — três tools MCP novas (`tarefa_criar`, `tarefa_listar`,
  `tarefa_concluir`), thin wrappers no mesmo padrão das tools de carteira (import tardio de
  `inpi.tarefas`, docstring com "USE QUANDO").
- `inpi/painel_dados.py` — `montar()` troca o placeholder de `tarefas` por dado real:
  `lista` (tarefas abertas) e `vencendo_7d` (recorte de `tarefas_vencendo(dias=7)`).
- `inpi/relatorio_html.py` — nova `_secao_tarefas()` substitui o placeholder: tabela de
  tarefas abertas com tag "Vence em 7 dias" nas que caem em `vencendo_7d`.

## Decisão: vigia novo vs. plugar direto

**Plugado direto no dashboard (`painel_dados.montar()`), sem 6º vigia em
`vigilancia/vigias.py`.** Tarefa leve é um lembrete interno — não depende de reingestão,
diff entre execuções, nem de nenhuma fonte externa; é uma leitura direta e barata da
própria tabela `tarefas`. Criar um vigia (que existe para orquestrar diff contra a última
execução e granular alertas por fonte externa) para isso inflaria `vigilancia/` sem
necessidade. `tarefas_vencendo()` é chamada direto por `painel_dados.montar()`, do mesmo
jeito que `_anuidades_90d()` já recorta `prazos_12m` sem passar por vigia.

## Pulado / adiado (e por quê)

- **E-mail de alerta de tarefa vencendo**: `vigilancia/executar.py`/`email_alerta.py` não
  foram tocados — o dashboard já mostra o recorte de 7 dias, e o plano só pede "aparece no
  dashboard e nos alertas", que a seção do dashboard cobre. Adicionar ao corpo do e-mail é
  extensão trivial se o operador pedir, não fica represado por decisão técnica.
- **Fase 4.8 (USPTO ODP)**: fora de escopo desta sessão — depende de `USPTO_API_KEY` que o
  Gabriel ainda vai criar (ID.me). Nenhum código tocado.
