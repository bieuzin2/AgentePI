# Migração da ficha-extras: pePI+Tor → Módulo de Serviços de Patentes + portal de estatística

## Contexto

Hoje `inpi/coleta_ficha_extras.py` + `inpi/coleta_sigilo.py` raspam o pePI legado
(`busca.inpi.gov.br/pePI`) atrás de um pool de daemons Tor locais
(`inpi/tor_proxy.py`), teto medido ~45-50 fichas/min. Já estava decidido mover o
backlog completo pra GitHub Actions (matrix de até 20 jobs, repo público
separado sem dado de cliente, escrita direta no MotherDuck via secret).

Investigação em duas sessões (`docs/pesquisa/inpi_plataforma_nova.md`) mapeou o
Módulo de Serviços de Patentes (`servicos.patentes.inpi.gov.br`), uma SPA em
beta que expõe via RPC proprietário ("Sydle") exatamente os dados que faltam
hoje na ficha-extras: biblio+CPC e a aba Anuidades (Anuidade, GRU, prazos,
valor pago, data de pagamento, situação da averbação). Nesta sessão, com o
usuário capturando o request real via DevTools (que meu fetch via console não
tinha replicado — faltava o campo `urlObjectId`, não `processNumber`),
confirmou-se que **todo o fluxo roda headless, sem navegador e sem Tor**:
login nativo PAG devolve um JWT reutilizável, e os três endpoints de dado
(biblio, eventos, anuidades) respondem 200 só com esse token.

Também foi descoberto `servicos.estatistica.inpi.gov.br`: portal público sem
login, com um dataset agregado nacional (~6078 linhas, por
ano/tipoAtivo/campoTecnológico/região/decisão) embutido em JS estático
(`db-data.js`+`db-engine.js`, codificado colunar). Não serve pro objetivo de
anuidades por processo, mas é fonte gratuita e sem risco pras tools de
mercado/landscape do projeto (`inpi_mercado`, `landscape_*`).

## Stream A — Módulo de Serviços de Patentes substitui pePI (corte validado)

### Login headless

```
POST https://servicos.patentes.inpi.gov.br/api/1/servicedesk-embedded/sys/auth/signIn/defaultAuthenticatorCustomer
Content-Type: application/json
{"userLogin": "<login da conta dedicada>", "userPassword": "<senha>"}
```

Resposta: `accessToken.token` (JWT) + `accessToken.payload.exp` (unix
timestamp de expiração). Usar `Authorization: Bearer <token>` nas chamadas
seguintes — testado sem cookies, funciona standalone. Relogar quando a
próxima chamada devolver 401 ou `exp` já tiver passado.

Conta: dedicada só pra automação, cadastro tipo "Cliente" em
`meu.inpi.gov.br` (não exige procuração de escritório real — confirmado na
sessão anterior).

### Endpoints de dado

Formato de `urlObjectId`/número de processo aceito: **12 dígitos, sem `BR`,
sem espaços, sem dígito verificador** (ex. `102022010731`).

| Dado | classId/método | body |
|---|---|---|
| Biblio + CPC | `_classId/68b1dda7671584537112aca5/getBibliographicData` (POST) | `{"processNumber": "<12 dígitos>"}` |
| Eventos de Pedido | `_classId/61bb893d05424e43e91eacd7/getListingData` (POST) | `{"componentId": "68b1f6ee6715845371898232", "customQuery": [], "customSort": null, "pageIndex": 0, "urlObjectId": "<12 dígitos>"}` |
| Anuidades | mesmo método | `{"componentId": "68b5e7a93cf0f00ea5057fb3", "customQuery": [], "customSort": null, "pageIndex": 0, "urlObjectId": "<12 dígitos>"}` |

`getBibliographicData` devolve array de campos INID (21/22/43/47/54/57/**51
classificação internacional**/**52 nacional**/71/72). `getListingData`
devolve `{total, objects: [{value: [...]}]}` — cada `value` é um array
posicional com as colunas visíveis na UI (pra Anuidades: Anuidade, GRU, prazo
ordinário, prazo extraordinário, valor pago, data de pagamento, situação da
averbação em HTML). **Mapear os índices desse array pra campos nomeados é
trabalho de implementação** — não foi feito nesta investigação, só
confirmado que a chamada devolve os dados certos.

`customQuery: []` (sem filtro) devolveu mais linhas de anuidade do que a UI
mostra por padrão (a UI aplica um filtro default, ex.
`endorsementStatus`/`readyToPay` visto no request capturado) — decidir na
implementação se replica esse filtro ou usa a lista completa sem filtro
(provavelmente preferível: sem filtro dá o histórico completo, o pePI atual
provavelmente já cobre isso).

### Validação de volume antes do corte

Antes de desativar o pePI+Tor: um job único roda **500-1000 processos** com a
conta dedicada, medindo:
- taxa de erro (429/403/CAPTCHA/mudança de schema)
- cobertura: comparar, pra processos com `data_deposito` nos últimos 30-60
  dias, se a plataforma nova já tem o processo indexado (hipótese do usuário:
  depósitos muito recentes podem só aparecer no pePI)

Só depois desse teste passar (taxa de erro aceitável, cobertura de recentes
equivalente) o backlog completo migra pra rodar só na plataforma nova, e o
cron do pePI+Tor é desligado.

### pePI+Tor: mantido como fallback, não apagado

`inpi/coleta_ficha_extras.py`, `inpi/coleta_sigilo.py` e `inpi/tor_proxy.py`
continuam no repo, intactos, documentados como fallback pra:
- depósitos recentes ainda não indexados na plataforma nova (se confirmado
  no teste de volume)
- contingência se a plataforma nova mudar o RPC sem aviso (é beta, não tem
  contrato de API público)

## Stream B — Portal de Estatística → MotherDuck

Cron periódico (mesmo padrão de `vigilancia/sync_motherduck.py`): baixa
`https://servicos.estatistica.inpi.gov.br/db-data.js` e `db-engine.js`,
decodifica o dataset colunar pro formato tabular (`window.pivotData` no
navegador: `{ano, tipoAtivo, subTipo, ..., depositos, concessoes, nDecisoes,
nVigentes}`), grava tabela nova no MotherDuck. `inpi_mercado`/`landscape_*`
passam a ler dessa tabela como fonte adicional — sem mudar a interface
pública dessas tools, só a fonte de dado por trás. **Decodificar o formato
colunar exato de `db-data.js`/`db-engine.js` é trabalho de implementação**
— nesta investigação só foi confirmado que `window.pivotData` (já decodificado,
acessível via JS no navegador) tem a forma certa; a implementação real vai
rodar fora do navegador, então precisa replicar a lógica de decodificação de
`db-engine.js` em Python, ou (mais simples/robusto) usar Playwright/Chrome
headless só nesse cron pra ler `window.pivotData` já pronto, evitando
reimplementar o decoder.

## Fora de escopo

- Fechar a exigência de CPF/documento no cadastro nativo `meu.inpi.gov.br`
  (não confirmado nesta investigação, mas não é bloqueador: cadastro tipo
  "Cliente" não exige procuração).
- Termos de Uso da plataforma nova (não encontrados; risco assumido, não
  mitigado).
- Mapeamento campo-a-campo dos arrays posicionais de `getListingData` e do
  formato colunar de `db-data.js` — fica pro plano de implementação.

## Verificação

- Stream A: script de teste de volume roda contra 500-1000 processos reais,
  relatório de taxa de erro + cobertura de recentes vs. pePI.
- Stream B: tabela nova no MotherDuck bate com os totais mostrados na UI do
  portal de estatística pra uma segmentação de controle (ex. Patentes, 2024).
