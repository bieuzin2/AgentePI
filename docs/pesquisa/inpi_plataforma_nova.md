# Plataforma nova do INPI (`servicos.patentes.inpi.gov.br`) como fonte de ficha-extras

Investigação de 2026-09-04, sessão logada com conta pessoal do usuário no
Módulo de Serviços de Patentes. Objetivo: decidir se essa plataforma substitui,
complementa, ou não vale o pePI+Tor+GitHub-Actions já desenhado pra raspagem
em massa de anuidades/petições (`inpi/coleta_ficha_extras.py`).

## 1. Mapa de API confirmado

Base: `https://servicos.patentes.inpi.gov.br/api/1/servicedesk-embedded/_classId/{classId}/{metodo}`
(framework proprietário "Sydle" — RPC por classId, não é REST convencional).

Formato do número de processo aceito pelos endpoints: **12 dígitos sem `BR`,
sem espaços, sem dígito verificador** (`102022010731`, não
`BR 10 2022 010731 2`). Testado contra processo real `102022010731`.

| classId | método | verbo | body/query | status testado | conteúdo |
|---|---|---|---|---|---|
| `68b1dda7671584537112aca5` | `getProcessNumber` | POST | `{"processNumber":"<12digitos>"}` | 200 | número formatado + tags (ex. "Prioritário") |
| `68b1dda7671584537112aca5` | `getBibliographicData` | POST | `{"processNumber":"<12digitos>"}` | 200 | array de 10 campos INID: nº pedido(21), depósito(22), publicação(43), concessão(47), título(54), resumo(57), **classificação internacional(51)**, **classificação nacional(52)**, depositante(71), inventores(72) |
| `61bb893d05424e43e91eacd7` | `getListingData` | POST | `{"componentId": "<id do widget>", ...}` — schema exato **não determinado** | 400 sem os params certos | é o método por trás das abas "Eventos de Pedido" e **"Anuidades"** (2 instâncias do componente `lvt-listing-objects` na página, uma por aba, cada uma com seu próprio `componentId`, capturado via DOM: `68b1f6ee6715845371898232` e `68b5e7a93cf0f00ea5057fb3`) |
| `645be3fb34d9110770e73fd8` | `getPageContent` | GET | query com `pathname`, `searchParams.processNumber` | 200 | conteúdo/layout da página, não dado de negócio |
| `61cc6dc56648f92b035af891` | `getDynamicConfig` | GET | `componentId` + `urlObject` | 200/400 conforme componentId | config de layout, não dado de negócio |

**Aba Anuidades confirmada visualmente** (via UI, não via chamada direta):
colunas Anuidade, GRU, Prazo ordinário, Prazo extraordinário, Valor pago,
Data de pagamento, Situação da averbação — exatamente a estrutura que falta
hoje na ficha-extras.

### Atualização 2026-09-04 (sessão 2): `getListingData` resolvido

O bloqueio acima foi fechado na mesma sessão em que o usuário capturou o
request real da UI via DevTools (Network tab, "Copy as cURL") clicando na
aba Anuidades de um processo carregado. O campo que faltava era
**`urlObjectId`** — não `processNumber`, não `urlObject`, não
`referenceObject._id` (nenhuma das mais de 10 variações testadas por HTTP
puro nesta sessão usava esse nome). Payload completo confirmado:

```json
{
  "componentId": "68b5e7a93cf0f00ea5057fb3",
  "customQuery": [],
  "customSort": null,
  "pageIndex": 0,
  "urlObjectId": "<numero 12 digitos>"
}
```
`componentId` é fixo por aba: `68b1f6ee6715845371898232` (Eventos de
Pedido) e `68b5e7a93cf0f00ea5057fb3` (Anuidades) — são IDs do widget
`lvt-listing-objects` na página, não mudam por processo. Resposta:
`{"total": int, "objects": [{"value": [...]}]}`, onde cada `value` é a
linha da tabela na ordem visível na UI (Anuidade, GRU, prazo ordinário,
prazo extraordinário, valor pago, data de pagamento, situação da averbação
em HTML).

**Login nativo também confirmado, 100% headless:**
```
POST /api/1/servicedesk-embedded/sys/auth/signIn/defaultAuthenticatorCustomer
{"userLogin": "...", "userPassword": "..."}
```
devolve `accessToken.token` (JWT) + `accessToken.payload.exp`. Testado
**sem cookies**, só `Authorization: Bearer <token>` — funciona standalone,
sem navegador, sem sessão prévia. Implementado em `inpi/plataforma_nova.py`.

`/swagger` em `servicos.patentes.inpi.gov.br` devolve 200, mas é falso
positivo: a SPA serve fallback 200 pra qualquer rota client-side (não é doc
real). Não achei OpenAPI/Swagger real em nenhum dos dois domínios.

## 2. Login: veredito

**Não é gov.br/SSO.** A autenticação real é via **PAG (Protocolo Automatizado
Geral)**, o sistema de login nativo do INPI — confirmado pela documentação
oficial ("Perguntas e Respostas — Módulo de Serviços de Patentes",
gov.br/inpi). A marca "gov.br" no cabeçalho da SPA é só o design system
padrão do governo, não OAuth via gov.br.

Cadastro em `meu.inpi.gov.br` (via `gov.br/inpi/pt-br/cadastro-no-e-inpi`) tem
dois fluxos:
- **"Cliente" (pessoa física/jurídica, próprio interessado)** — cadastro
  independente, **sem exigir procuração de escritório real**. Serve pra uma
  conta dedicada só de automação.
- **Procurador/advogado com procuração** — só pra quem representa terceiros.

Ou seja: **não há bloqueador de procuração** — dá pra criar conta nova
dedicada como "cliente" pessoa física. (A documentação pública não deixa
explícito se CPF é obrigatório no formulário, mas nada indica exigência de
vínculo com processos/clientes existentes.)

**Atualizado:** o usuário capturou o POST de login real (mesma técnica do
`getListingData`) — confirma exatamente o formato acima. Login headless
funcionando, implementado e testado.

## 3. Rate limits / Termos de Uso

Não achei página de Termos de Uso específica da plataforma nova (nem em
`gov.br/inpi` nem nos dois domínios técnicos). Durante a sessão (~15
requisições em poucos minutos, incluindo tentativas malformadas) não
observei nenhum sinal de bloqueio, CAPTCHA ou rate-limit — mas a amostra é
pequena demais pra concluir robustez em volume de produção (centenas de
milhares de processos).

## 4. API oficial pública

Existe: **`dadosabertos.inpi.gov.br`**, Plano de Dados Abertos do INPI
(Portaria INPI/PR nº 70/2022), com datasets de Patentes em CSV/ZIP + dicionário
de dados em ODT, licença Creative Commons. **Não é API REST** — é download de
arquivo em lote, sem indicação de conter anuidades pagas ou petições
protocoladas estruturadas (o conteúdo visível não confirma isso; precisaria
baixar um arquivo de amostra pra checar o dicionário de dados). Sem
OpenAPI/Swagger documentado em lugar nenhum.

## 5. Validação de volume (2026-09-04, rodada real)

`inpi/validar_plataforma_nova.py` rodou contra 530 processos reais já
cobertos pelo pePI (`ficha_extras`), amostra dividida entre "recentes"
(depósito nos últimos 45 dias) e "antigos", excluindo formato legado
`PIxxxxxxx` (a plataforma nova só aceita o formato moderno de 12 dígitos —
uma primeira rodada sem esse filtro tinha 13,6% de "erro" nos antigos, mas
100% eram números em formato legado, não falha real da API).

**Resultado, formato moderno apenas:**

| Grupo | Total | Sucesso | Indexado | Taxa |
|---|---|---|---|---|
| Recentes (≤45 dias) | 30 | 30 | 30 | 100% |
| Antigos | 500 | 500 | 500 | 100% |

Zero erros, zero exemplos de falha. A hipótese original do usuário
("depósitos recentes podem só estar no pePI") **não se confirmou** nesta
amostra — cobertura foi perfeita nos dois grupos. Nenhum sinal de
rate-limit/bloqueio em ~1600 requisições (530 processos × 3 chamadas)
concentradas em poucos minutos com uma única conta.

Limite da amostra: só cobre processos que o pePI já tinha coletado
(`ficha_extras`), então não testa processos que o pePI NUNCA viu.

## 5b. Formato legado (`PIxxxxxxx`) — testado, 2026-09-04

Amostra de 100 processos pré-2012 (`ficha_extras.numero_inpi LIKE 'PI%'`),
número passado **sem conversão** pro mesmo `getBibliographicData`:

| Total | Sucesso | Erro |
|---|---|---|
| 100 | 79 (79%) | 21 (21%) |

Achado inesperado: a plataforma nova **aceita o formato legado direto**,
sem precisar de conversão pro numérico moderno (que nem existe pra pedidos
pré-2012 — o dump do INPI só guarda `PIxxxxxxx` mesmo). Os 21% de erro são
"Pedido de patente não encontrado" — cobertura real incompleta pra formato
legado, não um problema de formato/payload. `inpi/validar_plataforma_nova.py`
tem `amostrar_legado`/`validar_legado` pra reproduzir/ampliar esse teste.

## 5c. Sigilo — o medo do usuário, testado e refutado

Preocupação original: pedidos em **sigilo** (~43 mil no dump, título/resumo
ocultos) têm o procurador só visível na ficha do pePI, nunca no dump aberto
— será que a plataforma nova também esconde isso?

**Caso concreto testado**: `102026015044` (PETRÓLEO BRASILEIRO/UFRJ,
depositado 17/06/2026, sem título publicado). `getBibliographicData` devolve
6 campos (21/22/43/47/71/74) — título e resumo (54/57) ausentes, como
esperado pro sigilo, mas **depositante e procurador aparecem normalmente**
(`CLARKE, MODET PROPRIEDADE INTELECTUAL LTDA.`). `getListingData` (anuidades)
também funciona pra esse processo.

**Amostra de 100 sigilo (formato moderno)**: 100/100 alcançável (`erro=0`).
Procurador presente em 41, ausente em 59 — à primeira vista parecia gap, mas:

**Teste pareado, a prova real**: 50 processos em sigilo cujo procurador o
**pePI já tinha coletado** (`procuradores` com `cgccpfprocurador IS NULL` =
veio da coleta de sigilo, não do dump aberto) comparados campo a campo
contra a plataforma nova — **50/50 bateram exatamente**. Ou seja: os 59%
"sem procurador" da amostra bruta não são um gap da plataforma nova — são
processos que genuinamente ainda não têm procurador vinculado (nem o pePI
tem). **O medo do usuário não se confirma**: sigilo está coberto, e quando
existe procurador, a plataforma nova mostra o mesmo valor que o pePI.
`inpi/validar_plataforma_nova.py` tem `amostrar_sigilo_com_procurador_conhecido`/
`validar_sigilo` pra reproduzir.

## 6. Comparação pePI+Tor vs. plataforma nova

| | pePI + Tor (atual) | Plataforma nova (RPC Sydle) |
|---|---|---|
| Requisições por processo | 2 (busca + GET ficha) | 3 (getBibliographicData + getListingData×2) |
| Parsing | HTML frágil | JSON estruturado |
| Autenticação | anônima | login PAG headless, testado sem cookies |
| Precisa de Tor | sim (IP direto já levou bloqueio) | não — zero bloqueio em ~1780 chamadas (530+100+50, sigilo+legado inclusos) |
| Cobertura formato moderno | completo | 100% confirmado (530/530) |
| Cobertura formato legado | completo | ~79% confirmado (79/100) — gap real, não de formato |
| Cobertura sigilo (procurador) | completo (fonte primária) | 100% alcançável, valor idêntico ao pePI quando existe (50/50 pareado) |
| Throughput testado | ~45-50 fichas/min | não medido em rajada máxima; ~700 processos em poucos minutos sem erro |

## 7. Opções de arquitetura

**A. Manter pePI+Tor+GitHub Actions como está.** Não faz mais sentido —
a plataforma nova está validada em moderno (100%), legado (79%) e sigilo
(100%), sem Tor.

**B. Plataforma nova substitui pePI inteiro, corte imediato, apaga o pePI.**
Ainda não recomendo apagar nada: o gap real de 21% no formato legado precisa
de um plano de fallback (não é zero, é um resíduo que precisa de tratamento).

**C. Corte por partes, pePI como fallback do resíduo — recomendado.** Já
implementado em `inpi/coleta_plataforma_nova.py` (reusa `registrar()` do
ficha-extras existente, mesmo CSV/schema):
1. **Formato moderno (recente + antigo)**: 100% validado (530/530) — migra
   sem ressalva.
2. **Sigilo**: coberto (100% alcançável, procurador idêntico ao pePI em
   teste pareado) — migra junto com o moderno, sem tratamento especial.
3. **Formato legado (`PIxxxxxxx`)**: 79% cobre direto (sem conversão) — migra
   pra plataforma nova como fonte primária; os ~21% que derem "não
   encontrado" caem pro pePI como fallback automático (não é preciso rodar
   o pePI pra tudo, só pro resíduo que a plataforma nova não resolver).

### Recomendação

Seguir com **C**, versão ampliada: a plataforma nova cobre moderno e
sigilo 100%, e legado 79% — o suficiente pra virar fonte PRIMÁRIA pros três
recortes, com o pePI acionado só quando a plataforma nova devolver "não
encontrado" (majoritariamente legado). Isso é uma mudança de arquitetura
mais simples que orquestrar duas fontes por tipo de processo: tentar
plataforma nova primeiro, sempre; cair pro pePI só no erro. `inpi/tor_proxy.py`
continua no repo, mas o uso dele cai drasticamente (só ~21% do legado, que
por sua vez é ~55% da base histórica — resíduo real: ~12% do total).

## Pendências pro usuário

1. **Decisão de produto**: aceitar o fallback automático plataforma-nova→pePI
   descrito acima como arquitetura final, ou insistir em entender os 21%
   de "não encontrado" no legado antes (pode ser pedido morto/arquivado há
   décadas que nem o pePI teria — não testado, os 21 exemplos de erro desta
   rodada não foram cruzados contra o status desses processos).
2. Throughput em rajada maior/paralelismo ainda não medido (~700 chamadas
   sequenciais nesta sessão, sem erro de rate-limit) — rodar com `tamanho`
   maior e paralelismo antes de migrar o backlog completo de centenas de
   milhares.
