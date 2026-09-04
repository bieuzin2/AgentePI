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
(`ficha_extras`), então não testa processos que o pePI NUNCA viu. E é
formato moderno apenas — cobertura de processos legado (`PIxxxxxxx`,
~55% da base histórica) na plataforma nova **continua desconhecida**.

## 6. Comparação pePI+Tor vs. plataforma nova

| | pePI + Tor (atual) | Plataforma nova (RPC Sydle) |
|---|---|---|
| Requisições por processo | 2 (busca + GET ficha) | 3 (getBibliographicData + getListingData×2) |
| Parsing | HTML frágil | JSON estruturado |
| Autenticação | anônima | login PAG headless, testado sem cookies |
| Precisa de Tor | sim (IP direto já levou bloqueio) | não — zero bloqueio em ~1600 chamadas |
| Cobertura de dado | anuidades+petições completo, qualquer formato | biblio+CPC+anuidades confirmado, **só formato moderno** (legado não testado) |
| Throughput testado | ~45-50 fichas/min | não medido em rajada máxima; 530 processos em poucos minutos sem erro |

## 7. Opções de arquitetura

**A. Manter pePI+Tor+GitHub Actions como está.** Não faz mais sentido como
única via — a plataforma nova está validada e sem Tor.

**B. Plataforma nova substitui pePI inteiro, corte imediato.** Arriscado:
não testamos cobertura de formato legado (~55% da base histórica) nem
volume em escala de produção (530 é uma amostra, não o backlog completo de
centenas de milhares).

**C. Corte validado, por partes — recomendado.** Já implementado em
`inpi/coleta_plataforma_nova.py` (reusa `registrar()` do ficha-extras
existente, mesmo CSV/schema). Rollout:
1. Processos formato moderno com depósito recente: já validado, pode migrar.
2. Processos formato moderno mais antigos: já validado (500/500), pode migrar.
3. Processos formato legado (`PIxxxxxxx`): **ainda não testado contra a
   plataforma nova** — pePI continua sendo a fonte até alguém rodar essa
   validação (adaptar `amostrar_processos` pra incluir `LIKE 'PI%'` e ver o
   que a API responde pra esse formato, provavelmente rejeitado).

### Recomendação

Seguir com **C**: migrar o formato moderno pra plataforma nova (já
implementado e validado, zero erro em 530 amostras), manter pePI+Tor vivo
só pro recorte legado até validar separadamente. `inpi/coleta_ficha_extras.py`/
`inpi/tor_proxy.py` continuam intactos no repo como fallback permanente
pra esse recorte, não como contingência temporária.

## Pendências pro usuário

1. Testar cobertura de formato legado (`PIxxxxxxx`) na plataforma nova —
   sem isso, não dá pra decidir se o pePI fica só como fallback de
   contingência ou como fonte permanente pra ~55% da base histórica.
2. Se quiser medir throughput em rajada maior (a validação rodou 530
   processos sequenciais com 0,2s de intervalo, não testou paralelismo nem
   volume de produção completo), rodar `validar_plataforma_nova.py` com
   `tamanho` maior antes de migrar o backlog inteiro.
