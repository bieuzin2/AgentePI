# Plano de refinamento — escopo final (2026-08-10)

## Contexto

Depois das correções da rodada anterior (EPO `fcntl`, `inpi_exigencias_escritorio`, composição
Clarke, cadência semanal-sábado), um agente-de-teste (persona: agente de PI da Clarke Modet)
varreu o escopo e escreveu `docs/pesquisa/apanhado-capacidades-2026-08-10.md`. Descoberta que
reenquadra tudo: **os servidores MCP em execução leem o banco atualizado (dados frescos, RPI
2900) mas ainda rodam o CÓDIGO de antes das correções** — eles carregam os módulos uma vez, no
start, e edições em arquivo não os recarregam. Prova: o `inpi_escritorio_resolver` ao vivo não
traz o bloco `composicao` que já está no código.

Consequência: metade dos "gaps críticos" do apanhado (EPO fcntl, exigências, composição,
`fila_semana=0`) já está resolvida no código e só espera **reload dos servidores + deploy**. A
outra metade é real e entra aqui. Decisões do brainstorming (2026-08-10):

- **Entram**: F0 (tornar vivo + processo de deploy), F1 (correções rápidas), F2 (landscape
  destravado).
- **Ficam de fora agora**: USPTO (não obter API key nesta rodada; US fora), valor em R$
  (`custos.yaml` adiado), busca semântica no INPI.

---

## F0 — Tornar as correções vivas + formalizar o deploy

O código corrigido não vale nada enquanto não chega ao agente. Passos:

1. **Local**: reiniciar os servidores MCP (ou o Claude Code) para recarregar `epo/`, `inpi/`,
   `landscape/`. Só então EPO, `inpi_exigencias_escritorio` e `composicao` ficam vivos localmente.
2. **Produção (Render)**: `git commit` + `git push` na `main` → deploy automático do
   `AgentePI` (ver `docs/agente-copilot.md`). É o que leva o código novo ao servidor remoto que
   o Copilot/Teams usa.
3. **Dados (MotherDuck)**: definir `MOTHERDUCK_TOKEN` no `.env` e rodar
   `python -c "from vigilancia.sync_motherduck import sincronizar; print(sincronizar())"` —
   senão o agente remoto continua na base antiga (a reingestão local já rodou; falta o push).
4. **Formalizar o processo** (o "corrigi mas não chegou" não pode repetir):
   - Um checklist de deploy versionado (`docs/deploy.md` ou seção em `docs/agente-copilot.md`):
     reload MCP local → testes verdes → push → confirmar deploy Render (`/health`) → sync
     MotherDuck → smoke test de 3 tools (EPO, exigências, composição) contra o remoto.
   - A vigilância de domingo (`vigilancia/executar.py`) já sincroniza **dados** ao MotherDuck; o
     **código** depende de push manual ao Render. Deixar isso explícito no checklist para não
     confundir "dados atualizados" com "código atualizado".

**Verificação F0**: contra o remoto, `inpi_escritorio_resolver("Clarke Modet")` traz
`composicao`; `epo_busca("ta=(covid)")` retorna total>0; `inpi_exigencias_escritorio` existe.

---

## F1 — Correções rápidas (todas entram)

1. **`busca_anterioridade` × `data_critica` — TypeError latente.**
   `busca/pipeline.py:199-203` faz `data < data_critica` onde `data` pode ser `date`/`datetime`
   (EPO/INPI real) e `data_critica` é string `'AAAA-MM-DD'` → `TypeError: date < str`. O teste
   não pega porque mocka `data` como string. **Fix**: coagir `data` a ISO-string antes do
   comparativo (`d = str(data)[:10]`), nas duas pernas (deduplicado e npl). Adicionar teste com
   `data` como objeto `date`.

2. **Falha silenciosa da perna EPO em `busca_anterioridade`.**
   Quando o EPO quebrava (fcntl), a perna reportava `executou: true, hits: 0` — indistinguível
   de "buscou e não achou". **Fix**: capturar a exceção da perna EPO e reportar
   `executou: false, erro: <motivo>` no bloco `cobertura`, como já se faz para `ppubs`
   (`pipeline.py:187-193`). Erro de fonte tem de aparecer como erro, nunca como vazio.

3. **Semântica do prazo em `inpi_prazos_carteira` / anuidades.**
   Hoje a data exibida pode ser o fim da **janela complementar** (art. 84 §2º, com retribuição
   adicional/"multa"), que se lê como "no prazo, tranquilo". **Fix**: em `inpi/anuidades.py` /
   `inpi/prazos.py`, anotar cada anuidade projetada com `janela` (`ordinaria` |
   `complementar_com_retribuicao`) e devolver também `fim_ordinario` e `fim_complementar`, para
   o agente dizer "já está no prazo complementar, com retribuição adicional".

4. **Reforço de expectativa (textos/instruções).**
   Confirmar em `docs/agente-copilot.md` e `docs/capacidades.md` que os limites estruturais
   estão explícitos: petição/cumprimento não publicados na RPI; validação Acordo de Londres
   invisível; cobertura DOCDB de jurisdições pequenas; `inpi_busca_texto` é ILIKE (literal), não
   semântica. Nenhum código — só garantir que o agente lidere com esses limites.

---

## F2 — Landscape destravado

**Problema**: `landscape/cache.py:_conectar()` abre um `_con` global em **read-write** no arquivo
local `landscape_cache.duckdb` (`cache.py:37`). O DuckDB local é single-writer: se outro
processo (outro servidor MCP, um órfão — foi visto o PID 12420, ~1,2 GB) tem o arquivo aberto
RW, toda `landscape_*` falha com `IO Error: cache travado por outro processo`. O mesmo motor
derruba o cross-check BigQuery de `inpi_perfil_titular` (`ConsultaMuitoGrandeError` é outro
sintoma da mesma indisponibilidade).

**Fix** (em `landscape/cache.py` + `landscape/bigquery_client.py`):
1. **Tolerância a lock na leitura**: em `obter()`, se abrir o arquivo local falhar por lock,
   reabrir `read_only=True` e servir o cache assim mesmo (leitura funciona mesmo com outro
   processo segurando o writer); `salvar()` que falhar por lock apenas loga e segue — nunca
   derruba a consulta. Com `MOTHERDUCK_TOKEN` (produção) o backend é `md:`, sem lock de arquivo,
   então isto é sobretudo blindagem de dev/local.
2. **Fechar conexões**: garantir `close()` do `_con` no encerramento e não deixar conexão órfã
   entre execuções (o PID 12420 é sintoma disso). Higienizar processos Python órfãos que seguram
   o arquivo.
3. **Cross-check de `inpi_perfil_titular`**: quando o BigQuery/landscape estiver indisponível,
   degradar com aviso claro ("2ª fonte indisponível — número só da base INPI"), nunca falhar a
   tool inteira.

**Verificação F2**: `landscape_top_titulares` retorna dados; `inpi_perfil_titular` de titular
grande (ex.: Huawei) completa com ou sem o cruzamento BigQuery, sempre com aviso quando sem.

---

## Fora do escopo (registro da decisão)

- **USPTO**: não obter `USPTO_API_KEY` nesta rodada; US fica de fora. PPUBS instável e ODP/PTAB
  bloqueados por credencial ficam como pendência futura registrada.
- **Valor em R$ (`custos.yaml`)**: adiado. `financeiro_projecao`/`fila_semana` seguem contando
  eventos, com o aviso de que não é fatura.
- **Busca semântica no INPI**: `inpi_busca_texto` segue ILIKE (literal). Alto esforço, fora.
- **Limites estruturais de fonte** (petição, Acordo de Londres, cobertura DOCDB): não são
  engenharia; tratados só como expectativa (F1.4).

---

## Verificação end-to-end

- **F0**: smoke test das 3 tools corrigidas contra o **remoto** após deploy+sync; `/health` do
  Render ok; `inpi_cobertura` no remoto mostra RPI 2900.
- **F1**: `pytest busca` verde incluindo o novo teste de `data_critica` com objeto `date`;
  `inpi_prazos_carteira` de um cliente mostra `janela` por anuidade.
- **F2**: `pytest landscape` verde; `landscape_top_titulares` e `inpi_perfil_titular` (titular
  grande) respondem sem travar; simular lock (2ª conexão RW) e ver a leitura cair para read_only
  em vez de falhar.
- **Global**: `python -m pytest epo inpi vigilancia remoto busca landscape -q` verde.
