# Evidência de aceite — Fase 1 (Vigilância Autônoma + Anuidades)

Ref.: `docs/plano-v2.md` seções 4.1 e 4.2, tabela §6 linha "Fase 1".

## Baseline (antes)

```
.venv/Scripts/python.exe -m pytest epo inpi -q
129 passed in 157.76s
```

## Comandos rodados

```
pip install pyyaml            # nova dependencia (config.yaml)
pip install -e .               # pyproject.toml passou a listar tambem o pacote vigilancia
.venv/Scripts/python.exe -m pytest vigilancia -q                     # 12 passed
.venv/Scripts/python.exe -m pytest epo inpi vigilancia -q            # 141 passed in 185.77s
.venv/Scripts/python.exe -m vigilancia.executar --dry-run --sem-reingestao --hoje 2026-08-05
```

Saída do dry-run (contra a base real, watchlist `PI0803071`/`B65D`/`PETROLEO BRASILEIRO`
de `vigilancia/config.yaml`):

```json
{
  "executado_em": "2026-08-05",
  "desde": "2026-07-29",
  "total_alertas": 1,
  "gravados": 1,
  "alertas_md": "vigilancia/data/alertas.md",
  "vigia_exterior_rodou": false,
  "email": {
    "enviado": false,
    "dry_run": true,
    "mensagem": "[dry-run] e-mail NAO enviado. ..."
  },
  "dry_run": true
}
```

`inpi_alertas()` confirmado lendo e marcando como visto:

```
total_no_banco=1 nao_vistos=1 -> apos marcar_vistos -> nao_vistos=0
```

## Resultado final

```
141 passed in 185.77s (0:03:05)
```

Sem regressão nos 129 testes de `epo`/`inpi`; 12 testes novos em `vigilancia/`.

## Commits

1. `feat(vigilancia): estrutura do pacote, config.yaml, reingestao`
2. `feat(vigilancia): 5 vigias com deteccao de despachos e anulacao`
3. `feat(vigilancia): orquestracao, email de alerta, tool MCP inpi_alertas`
4. `feat(vigilancia): agendamento Task Scheduler + testes fim a fim`
5. `docs: evidencia de aceite Fase 1` (este arquivo + `docs/capacidades.md`)

## O que foi entregue

- `vigilancia/config.yaml` — watchlists (carteira, titulares concorrentes, IPCs, e-mail).
- `vigilancia/reingestao.py` — reusa `inpi/ingest.py` (baixar + main), registra data de corte.
- `vigilancia/vigias.py` — 5 vigias:
  1. carteira (despacho novo + detecção de anulação, severidade alta) — validado com o
     caso real `PI0803071` (RPI 2897 despacho `21.6` anulado pelo `21.8` da RPI 2898).
  2. concorrentes (`inpi_portfolio_titular`).
  3. IPC (`inpi_busca_ipc`).
  4. anuidades — janela 90 dias (`inpi_prazos_carteira`), diff contra estado anterior
     persistido em `vigilancia/data/estado_anuidades.json`.
  5. exterior — mensal (`primeira_terca_do_mes`), status legal INPADOC via
     `inpi/familia_epo.py` + `epo/epo_mcp.py::epo_status_legal`.
- `vigilancia/executar.py` — orquestração + `--dry-run` + `--sem-reingestao` + `--sem-email`
  + log de execução (`log_execucoes.jsonl`, base para o alerta de Task Scheduler silencioso,
  risco da seção 9 do plano).
- `vigilancia/email_alerta.py` — SMTP Gmail via `smtplib` (stdlib), credenciais em `.env`
  (`SMTP_USER`/`SMTP_PASS`, documentadas em `.env.example`).
- `inpi/inpi_mcp.py::inpi_alertas` — tool MCP nova, lê/marca alertas de `alertas.duckdb`.
- `scripts/instalar_agendamento.ps1` — Task Scheduler, terça 20h semanal.
- `docs/lgpd.md` — parágrafo sobre o corte de dado pessoal nos e-mails de alerta.
- `inpi_anuidades` (`inpi/prazos.py`, já existente da Fase 0) conferido: já devolve
  data-base, `base_legal` por vencimento e `vigencia_publicada_16_1` — nenhuma mudança de
  lógica foi necessária (4.2 do plano).

## Pulado / adiado (e por quê)

- **Integração com o dashboard** (`inpi/relatorio_html.py`): a função `gerar()` só aceita
  `procurador` e não tem gancho para uma seção "alertas da semana" — criar essa integração
  agora seria inventar uma interface frágil por cima de um módulo que a Fase 2 (4.3) vai
  reescrever de qualquer forma. Ponto marcado com `TODO(Fase 2)` em `vigilancia/executar.py`.
- **Credencial SMTP real**: `SMTP_USER`/`SMTP_PASS` ficam vazias no `.env` até o Gabriel
  gerar a senha de app do Gmail (pré-requisito do plano, seção 10.8). O código já lê de
  variável de ambiente e falha com mensagem clara se ausente; testado via `--dry-run`, que
  não depende da credencial.
- **CSVs reais para teste de `reingestao.py`**: sem mock de rede (regra do plano), o
  teste de `executar.py --dry-run` roda com `--sem-reingestao` contra a base já ingerida
  localmente, em vez de baixar CSV de verdade a cada `pytest`.

## Pendente para a Fase 2 (dashboard, plano §4.3 — fora de escopo desta fase)

Concluído na Fase 2 — ver `docs/aceite/F2-dashboard.md`.
