# Evidência de aceite — Fase 2 (Dashboard do Escritório)

Ref.: `docs/plano-v2.md` seção 4.3, tabela §6 linha "Fase 2".

## Baseline (antes)

```
.venv/Scripts/python.exe -m pytest epo inpi vigilancia -q
141 passed in 226.29s (0:03:46)
```

## Comandos rodados

```
.venv/Scripts/python.exe -m pytest epo inpi vigilancia -q
.venv/Scripts/python.exe -m vigilancia.executar --dry-run --sem-reingestao --hoje 2026-08-05
```

Saída do dry-run (contra a base real):

```json
{
  "executado_em": "2026-08-05",
  "desde": "2026-08-05",
  "total_alertas": 0,
  "gravados": 0,
  "alertas_md": "vigilancia\\data\\alertas.md",
  "dashboard": {
    "arquivo": "docs\\relatorios\\panorama_clarke_modet.html",
    "tamanho_mb": 7.59,
    "total_casos": 44642
  },
  "vigia_exterior_rodou": false,
  "email": {"enviado": false, "dry_run": true, "mensagem": "[dry-run] e-mail NAO enviado. ..."},
  "dry_run": true
}
```

Confirma o TODO(Fase 2) resolvido: `executar()` agora devolve a chave `dashboard` e o
arquivo HTML foi regenerado de fato (mesmo timestamp da execução), sem precisar de
servidor -- abre direto no navegador.

## Resultado final

```
145 passed in 314.08s (0:05:14)
```

Sem regressão nos 141 testes anteriores; 4 testes novos em `inpi/test_painel_dados.py`
(alertas sem banco, alertas lidos do duckdb sintético, recorte de anuidades 90d,
placeholders de tarefas/landscape).

## Commits

1. `973f2e5` `refactor(dashboard): extrai camada de dados painel_dados.py`
2. `fef8dac` `feat(dashboard): secoes de alertas e anuidades, template quebrado por secao`
3. `c98948e` `feat(vigilancia): conecta executar.py a regeneracao do dashboard`
4. `docs: evidencia de aceite Fase 2` (este arquivo)

## O que foi entregue

- `inpi/painel_dados.py` — camada de dados única do dashboard: `montar()` embrulha
  `panorama_carteira.panorama()` (já existia, já testado) e acrescenta:
  - `alertas_semana` — lê os últimos alertas gravados de `vigilancia/data/alertas.duckdb`
    ([] se o arquivo ainda não existir — dashboard tem que abrir mesmo antes da primeira
    execução agendada).
  - `anuidades_90d` — recorte do `prazos_12m` que `panorama()` já projeta (tipo `anuidade`,
    prazo ≤ 90 dias); não reconsulta o banco.
  - `tarefas` / `landscape` — placeholders com nota `TODO`, apontando para as Fases 6
    (plano 4.7) e 5 (plano 4.6), que ainda não existem.
- `inpi/relatorio_html.py` — `gerar()` consome `painel_dados.montar()`; ganhou 4 seções
  novas renderizadas em Python (estáticas, não entram na segmentação client-side porque
  são snapshot do dia, não dimensão por caso): alertas da semana, anuidades 90 dias,
  tarefas (placeholder), landscape (placeholder). CSS e JS movidos para
  `relatorio_html_css.py` / `relatorio_html_js.py` — o arquivo original passava de 500
  linhas (regra do CLAUDE.md); nenhuma lógica de gráfico/filtro mudou, só o arquivo.
  Design das seções novas (tags de severidade alta/média/baixa, cards de placeholder
  tracejados "ainda não implementado") validado com a skill `ui-ux-pro-max`.
- `vigilancia/executar.py` — resolvido o `TODO(Fase 2)`: depois de `gravar_alertas()`,
  chama `relatorio_html.gerar(hoje=ref, banco_alertas=str(BANCO), saida=destino_dashboard)`.
  Não precisa passar a lista de alertas por parâmetro — `painel_dados` lê direto do banco
  já gravado. `destino_dashboard` é opcional (testes usam `tmp_path`; execução real usa o
  caminho padrão em `docs/relatorios/`).
- Continua abrindo no navegador, zero servidor — comportamento herdado, não mudou.

## Pulado / adiado (e por quê)

- **Unificar `relatorios.py` (PDF/XLSX de prazos) na mesma `painel_dados.py`**: o plano
  descreve "triplicação de renderizadores", mas na prática o PDF/XLSX de prazos responde a
  um recorte de datas arbitrário escolhido na hora (`--de`/`--ate`), não ao snapshot fixo do
  dia que o dashboard mostra — são dados de formato diferente. Forçar os dois no mesmo dict
  seria inventar uma abstração para dado que não é o mesmo dado. `relatorios.py` ficou
  intocado.
- **Tabela de tarefas real**: fora de escopo (Fase 6, plano 4.7) — seção do dashboard
  existe, vazia, com nota `TODO` explícita.
- **Gráficos de landscape**: fora de escopo (Fase 5, plano 4.6) — mesma coisa, placeholder.
- **JS novo para as 4 seções**: renderizadas em Python (string HTML direta), não em
  `relatorio_html_js.py` — não precisam de segmentação client-side, então JS a mais seria
  código sem função.

## Pendente para Fases 3/4 (fora de escopo desta fase, independentes entre si)

- **Fase 3** (`busca/pipeline.py`, plano 4.4): pipeline de busca de anterioridade
  (INPI + EPO + PPUBS + OpenAlex, dedup por família INPADOC) — não implementado.
- **Fase 4** (`inpi/pdf_inpi.py`, plano 4.5): download/parse de PDF INPI + claim chart BR —
  não implementado.
