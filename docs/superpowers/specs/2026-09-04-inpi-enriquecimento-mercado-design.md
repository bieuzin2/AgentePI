# Enriquecimento de mercado (concorrentes → base nacional) — Design

## Contexto

O sistema de coleta incremental existente (`vigilancia/incremento_plataforma_nova.py`,
spec `2026-09-04-inpi-incremento-e-migracao-design.md`) é deliberadamente
escopado à carteira própria (CLARKE MODET) e limitado por rodada — por
design, não cobre enriquecimento em nível de processo (CPC completo,
anuidades pagas, petições) de patentes de terceiros.

Motivo de negócio pra esse enriquecimento fora da carteira: (1) prospecção/
vigilância de concorrentes específicos em nível de processo, não só
agregado; (2) base de benchmark mais rica que `estatistica_nacional`
(contagem por ano/setor), permitindo cruzar por titular/procurador/IPC fino.

Meta final: cobrir os ~153.200 depósitos nacionais dos últimos 6 anos
(2020-2026). Rollout faseado: começa pelos maiores concorrentes da Clarke
Modet (derivados automaticamente por volume/coocorrência de IPC), expande
pro restante da base nacional quando o usuário decidir "fechar o escopo".

**Fora de escopo, decisão explícita:** nenhuma técnica de evasão de bloqueio
(rotação de IP via Tor, distribuição de origem via múltiplas máquinas/CI
pra parecer tráfego distribuído, insistência automática contra bloqueio
deliberado do INPI). O que existe aqui é resiliência a falha transitória
(retry/backoff, checkpoint/retomada) — não contorno de proteção anti-abuso
de um site do governo. Ver decisão de isolar credencial abaixo.

## Arquitetura

Processo novo e independente do job semanal (`vigilancia/executar.py` não é
tocado). Reusa `ClientePlataformaNova`/`coletar_com_fallback_pepi` já
existentes (`inpi/plataforma_nova.py`, `inpi/coleta_plataforma_nova.py`) —
só muda quem popula a lista de `numero_inpi`, como o progresso persiste
entre execuções, e a atribuição (`escritorio_canonico=None`, não
"CLARKE MODET").

**Credencial isolada:** `INPI_PAG_LOGIN_MERCADO`/`INPI_PAG_PASSWORD_MERCADO`
no `.env`, login PAG separado da produção (mesmo mecanismo de
`inpi/plataforma_nova.py::ClientePlataformaNova`, credencial diferente). Um
possível bloqueio/throttle nesta conta não afeta o job semanal de produção
da carteira, que usa `INPI_PAG_LOGIN`/`INPI_PAG_PASSWORD`.

## Componentes

### `inpi/mercado_fila.py` (novo)

Gerencia a fila persistente em `inpi/data/fila_mercado.duckdb` (arquivo
próprio, separado de `inpi.duckdb` — zero risco de lock/concorrência com o
job semanal). Schema: `fila_mercado(numero_inpi VARCHAR, origem VARCHAR,
status VARCHAR, tentativas INTEGER, atualizado_em VARCHAR)`.

- `popular_concorrentes()`: deriva lista de titulares concorrentes via
  `landscape_co_classificacao`/`landscape_top_titulares` (já existentes),
  insere `numero_inpi`s desses titulares com `origem='concorrente'`,
  `status='pendente'`.
- `popular_nacional()`: insere o resto dos ~153k (depósito últimos 6 anos,
  ainda não presentes na fila) com `origem='nacional'`. Só rodar quando o
  usuário decidir expandir além dos concorrentes.
- `proximo_lote(n) -> list[str]`: pendentes, ordenado por `origem`
  (concorrente antes de nacional), limitado a `n`.
- `marcar(numeros_inpi, status)`: atualiza status em lote
  (`coletado`/`bloqueado`/`erro`).

### `inpi/coleta_mercado.py` (novo)

Loop principal, CLI simples (`python -m inpi.coleta_mercado`, sem flag em
`executar.py` — deliberadamente fora do ciclo semanal):

1. Autentica com credencial `_MERCADO`.
2. `proximo_lote(N)` (N configurável, default a decidir no plano).
3. `coletar_com_fallback_pepi(cliente, lote, escritorio_canonico=None, ...)`.
4. Grava resultado em `ficha_extras` (via `registrar()` já existente, sem
   mudança de schema) e marca fila.
5. Dorme o intervalo necessário pra manter ritmo ~45-50 fichas/min
   (throughput testado, ver `docs/pesquisa/inpi_plataforma_nova.md` seção 6).
6. Se proporção de `erros` no lote passar de um limiar (a definir no plano,
   ex. >30%) → marca pendentes restantes do lote como `bloqueado`, loga
   claramente, **encerra o processo**. Não insiste sozinho contra bloqueio.
7. Repete a partir do passo 2 até a fila esvaziar ou travar.

Interrupção manual (Ctrl+C) ou queda de máquina é segura: `registrar()` já
grava linha a linha no CSV, e a fila marca item por item — retoma sozinho
na próxima chamada, sem replay do que já foi feito.

### Ajuste em `inpi/coleta_plataforma_nova.py::coletar_e_registrar` (produção)

Hoje o `except` por item pega só `PlataformaNovaError` — erro de rede cru
(timeout, conexão caída) propaga e mata o lote inteiro sem aviso. Ajustar
pra `except (PlataformaNovaError, httpx.HTTPError)`, contando como `erros`
em vez de propagar. Correção de bug compartilhada: beneficia o job semanal
de produção também (nunca tinha esse gap coberto).

### `escritorio_canonico=None`

Confirmado contra o código real: nenhuma tool (`inpi_anuidades_pagas`,
`inpi_peticoes_escritorio`, `inpi/consulta.py`) filtra
`WHERE escritorio_canonico = X` — todas escopam por carteira via JOIN em
`procuradores`/`escritorios` (chave canônica), não pela coluna
`ficha_extras.escritorio_canonico`. `None` (grava como string vazia via
`csv.DictWriter`) não quebra nada existente.

## Testes

- `inpi/test_coleta_plataforma_nova.py`: erro de rede genérico (não só
  `PlataformaNovaError`) conta como `erros`, não propaga e não mata o lote.
- `inpi/test_mercado_fila.py` (novo): popular/próximo_lote/marcar contra
  fila em `tmp_path`, sem rede.
- `inpi/test_coleta_mercado.py` (novo): loop com cliente mockado — lote com
  erro acima do limiar → para e marca bloqueado; lote ok → continua e
  processa o próximo.
- Sem teste de integração real contra a plataforma nova (precisa de
  credencial de verdade) — mesma convenção do resto do repo.

## Pendências pro plano de implementação

- Tamanho de lote (N) e limiar de bloqueio (% erro) — número exato a
  decidir na escrita do plano, não neste spec.
- Confirmar disponibilidade da segunda credencial PAG
  (`INPI_PAG_LOGIN_MERCADO`) antes de codar o consumo dela — se ainda não
  existe, é passo manual do usuário antes do primeiro uso real (o código
  funciona sem, só falha com mensagem clara de credencial ausente, mesmo
  padrão do resto do repo).
- `popular_concorrentes()` depende de `landscape_co_classificacao`/
  `landscape_top_titulares` já cobrirem os campos tecnológicos certos da
  carteira Clarke Modet — não verificado neste brainstorm, verificar ao
  escrever o plano.
