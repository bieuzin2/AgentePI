# Contrato de fontes da RPI — INPI

Levantado em 2026-07-25 a partir dos metadados oficiais do conjunto
`revista-da-propriedade-industrial-rpi` em dados.gov.br
(`GET https://dados.gov.br/api/publico/conjuntos-dados/revista-da-propriedade-industrial-rpi`,
público, sem chave).

---

## 🔴 Correção de premissa: a RPI de Patentes **não** tem XML

O relatório `deep.md` e o protótipo anterior assumiram que o INPI publica a seção de
Patentes em XML. **Não publica.** A documentação oficial do próprio conjunto de dados:

| Seção | Formatos disponíveis | Desde |
| :--- | :--- | :--- |
| **VI — Patentes** | **PDF e ZIP+TXT** | RPI 1132 (10/ago/1992) |
| V — Marcas | PDF e **ZIP+XML** | RPI 2220 (23/jul/2013) |
| II — Contratos de Tecnologia | PDF e ZIP+TXT | RPI 2404 (31/jan/2017) |
| III — Desenhos Industriais | PDF e ZIP+TXT | RPI 2404 |
| VII — Programas de Computador | PDF e ZIP+TXT | RPI 2404 |

**XML só existe para Marcas.** Isso explica por que o protótipo anterior inventou um
schema XML: não havia XML de patentes para copiar. O parser da Trilha B é de **TXT
posicional/delimitado por códigos**, não de XML — e o insumo de referência é a seção
"Códigos e Abreviações" em `revistas.inpi.gov.br` (códigos de despacho + códigos INID),
não um manual de layout XML.

Em 31/jan/2017 (RPI 2404) Contratos, Programas de Computador e Topografia foram
desmembrados da seção de Patentes. Revistas anteriores a essa data têm estrutura
diferente — se a ingestão for retroagir, são dois parsers, não um.

## Índice de revistas (JSON)

`GET http://revistas.inpi.gov.br/rpi/busca/data`

| Parâmetro | Valor |
| :--- | :--- |
| `revista.dataInicial` | `31/01/2017` (formato DD/MM/AAAA) |
| `revista.dataFinal` | `31/12/2200` |
| `revista.tipoRevista.id` | **6 = Patentes** · 5 = Marcas · 3 = Desenhos Industriais · 2 = Contratos · 7 = Programas de Computador |

Devolve, para cada revista: número, data de publicação, `nomeArquivo` (PDF) e
`nomeArquivoEscritorio` (ZIP). **A data de publicação vem daqui** — é a âncora legal de
todo cálculo de prazo, e é o campo que o protótipo anterior descartou.

## Download dos arquivos

| Formato | URL | Exemplo (RPI 2403) |
| :--- | :--- | :--- |
| ZIP+TXT | `revistas.inpi.gov.br/txt/{nomeArquivoEscritorio}` | `http://revistas.inpi.gov.br/txt/P2403.zip` |
| ZIP+XML *(só marcas)* | `revistas.inpi.gov.br/xml/{nomeArquivoEscritorio}` | — |
| PDF | `revistas.inpi.gov.br/pdf/{nomeArquivo}` | `http://revistas.inpi.gov.br/pdf/PATENTES2403.pdf` |

Publicação semanal às terças. Numeração sequencial e incremental.

## Estrutura interna do TXT

Baseada em **códigos de despacho** e **códigos INID**, documentados em
`http://revistas.inpi.gov.br`, seção "Códigos e Abreviações". Esse é o contrato a
confrontar com o censo do arquivo real — o equivalente ao "manual de layout" que o plano
previa.

> ⚠️ O ZIP+TXT contém "informações simplificadas da RPI" — **não inclui os comunicados do
> Instituto** (Seção I). Para monitoramento de despachos isso basta; para acompanhar
> comunicados normativos, não.

---

## 🚧 Bloqueio de rede (2026-07-25)

`revistas.inpi.gov.br` (168.90.175.178) e `busca.inpi.gov.br` (168.90.175.139) **não são
alcançáveis desta máquina.**

Diagnóstico executado:

| Teste | Resultado |
| :--- | :--- |
| DNS | ✅ resolve |
| TCP 443 e 80 | ✅ conecta |
| TLS 1.0 / 1.1 / 1.2 / 1.3, forçados um a um | ❌ todos resetam |
| TLS sem SNI | ❌ reseta |
| TLS com `verify_mode=CERT_NONE` e `@SECLEVEL=0` | ❌ reseta |
| curl (schannel) | ❌ `failed to receive handshake` |
| Chromium (browser embutido) | ❌ navegação falha |
| `www.gov.br`, `dados.gov.br` (comparação) | ✅ TLS 1.3 OK |

O servidor aceita o TCP e derruba durante o handshake TLS, independentemente de versão,
cifra ou SNI. Não é configuração do cliente — é bloqueio ou indisponibilidade no lado do
INPI (WAF por ASN/geografia, ou serviço fora do ar).

**Consequência:** o censo do arquivo real (B0) não pode ser feito daqui. E a disciplina do
plano é explícita — **não escrever parser antes de ver um arquivo real**. O protótipo
anterior violou exatamente isso e produziu um parser que retorna zero em silêncio.

### Como destravar (ordem de preferência)

1. **Baixar manualmente pelo navegador do Gabriel** — se a rede dele alcança o INPI:
   abrir `http://revistas.inpi.gov.br/rpi/`, baixar o ZIP+TXT da seção Patentes de uma
   terça recente, e salvar em `inpi/data/raw/rpi/`. Um arquivo já destrava o censo.
2. **Rodar a ingestão de outra rede** (celular como roteador, VPS no Brasil) — confirma se
   o bloqueio é por IP/ASN.
3. **Confirmar que não é indisponibilidade temporária** — repetir o diagnóstico em outro dia.

Enquanto não houver um arquivo real em mãos, a Trilha B fica parada em B0. A Trilha A
(USPTO, e a seguir EPO OPS) não depende disto e segue.
