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

### O que não foi resolvido
`getListingData` (o endpoint que traz Eventos e Anuidades) exige o
`componentId` do widget **mais** algum contexto de sessão que não é só
`processNumber` no body — testei mais de 10 combinações de payload
(`processNumber`, `urlObject`, `filter`, `context`, replay de
`getPageContent` antes da chamada) e todas retornaram
`[formatProcessNumber] Necessário informar o número do processo`, um erro
gerado **no backend** (stack trace `com.levty.levtyComponents...`), não no
bundle JS que dá pra grepar. Isso sugere que o dado do processo é resolvido
no servidor a partir de estado de sessão associado à navegação completa (não
só o body do POST), o que **não é uma chamada HTTP standalone trivial** —
precisaria de mais engenharia reversa (proxy MITM na sessão real do
navegador, não só grep de bundle) pra fechar o payload exato.

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

**Não testei o POST de login em si** (usuário/senha → token/cookie) porque a
sessão do navegador já estava autenticada, e inspecionar o formulário de
login exigiria deslogar — o que eu não faço, por não poder inserir senha em
nome do usuário (regra de segurança desta sessão). Ação pendente pro usuário:
abrir uma aba anônima, ir até a tela de login nativo (usuário/senha, "não é
gov.br"), abrir DevTools → Network, submeter o login manualmente, e me
mandar o request (URL, body, resposta) capturado — com isso dá pra confirmar
se é um POST simples reproduzível via `requests`/`httpx`.

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

## 5. Comparação pePI+Tor vs. plataforma nova

| | pePI + Tor (atual) | Plataforma nova (RPC Sydle) |
|---|---|---|
| Requisições por processo | 2 (busca + GET ficha) | pelo menos 3 (getProcessNumber + getBibliographicData + getListingData×2, se o payload for resolvido) |
| Parsing | HTML frágil | JSON estruturado (biblio confirmado; anuidades ainda não replicável fora do navegador) |
| Autenticação | anônima | login PAG obrigatório, sessão por conta |
| Precisa de Tor | sim (IP direto já levou bloqueio) | desconhecido — nenhum bloqueio observado, mas teste foi pequeno e logado com sessão de navegador real, não em massa |
| Cobertura de dado | anuidades+petições completo hoje | biblio+CPC confirmado; **anuidades só confirmado via UI**, não via chamada HTTP direta ainda |
| Throughput testado | ~45-50 fichas/min | não testado em volume |

## 6. Opções de arquitetura

**A. Manter pePI+Tor+GitHub Actions como está, ignorar a plataforma nova por
ora.** Menor risco, zero trabalho novo, mas continua limitado a ~45-50/min e
depende de scraping de HTML frágil e Tor.

**B. Plataforma nova substitui pePI inteiro.** Só vale a pena SE alguém
fechar o payload de `getListingData` (a parte que faltou nesta sessão) e
confirmar que o rate-limit por conta aguenta volume de produção sem bloqueio.
Hoje é uma aposta, não um plano executável.

**C. Híbrido — recomendado.** Usar a plataforma nova só pra biblio/CPC
(`getBibliographicData`, já 100% funcional e replicável em `requests` puro,
sem Tor, sem parsing de HTML) e manter pePI+Tor pra anuidades/petições até
alguém investir o tempo de reverse-engineering do `getListingData` (ou obter
a especificação direto com o INPI/suporte). Ganho imediato e de baixo risco:
tira carga do pePI pro que já está resolvido, sem apostar o backlog inteiro
numa API cujo endpoint principal (anuidades) ainda não foi fechado.

### Recomendação

Seguir com **C**: pipeline GitHub Actions já desenhado continua carregando
anuidades/petições via pePI+Tor sem mudança; abrir uma tarefa separada,
pequena e de baixo risco, pra usar `getBibliographicData` (login PAG com
conta dedicada nova) como fonte alternativa de CPC/biblio — sem tocar no
que já funciona. Só reconsiderar B se o `getListingData` for fechado e um
teste de volume real (centenas de chamadas seguidas, mesma conta) não mostrar
bloqueio.

## Pendências pro usuário

1. Capturar o POST de login nativo (usuário/senha) numa aba anônima e me
   mandar request+resposta.
2. Se quiser perseguir a via B, alguém precisa investigar `getListingData`
   com um proxy MITM (mitmproxy/Charles) na sessão real do navegador — grep
   de bundle client-side não foi suficiente porque a validação é no backend.
