# Agente de Patentes — como usar

Bancada de busca de anterioridade e exame de patenteabilidade rodando em **Claude Code**,
nesta pasta. Você conversa em português; o agente busca nas bases oficiais e monta o
quadro de confronto.

## Primeira vez

```bash
claude
```

Rode dentro de `C:\Users\Gabriel\Desktop\Patentes`. Na primeira execução o Claude Code
pede aprovação dos servidores MCP declarados em `.mcp.json` — aceite os três (`uspto`,
`epo`, `inpi`). Confira com `/mcp`: os três devem aparecer como *connected*.

**Depois de editar `.mcp.json` ou `.env`, reinicie o Claude Code.** Os servidores sobem
uma vez, no início da sessão.

## O que está ligado

| Servidor | Cobre | Credencial |
| :--- | :--- | :--- |
| `uspto` | patentes e pedidos dos EUA, texto integral, PTAB | nenhuma (PPUBS é público) |
| `epo` | **BR, CN, EP e +100 jurisdições** via INPADOC/DOCDB | `EPO_OPS_KEY` + `EPO_OPS_SECRET` ✅ |
| `inpi` | **Brasil**: texto, andamento e 5,3 M despachos, 1972→hoje | nenhuma (base local) ✅ |

O `lens` **saiu do escopo**. O código continua em `lens/`, desligado — a decisão é
reversível. Razão: o trial só liberou a Patent API, e patente o EPO OPS já cobre de graça,
com dado oficial e família INPADOC (`docs/aceite/A3-lens.md`). O único diferencial seria a
Scholarly API (literatura não-patentária), que devolveu 401. Para religar, recoloque o
bloco `lens` no `.mcp.json`.

Faltando só `USPTO_API_KEY` (destrava andamento e PTAB dos EUA — a busca funciona sem ela).

### Atualizar a base do INPI

Os dados abertos saem todo dia; a RPI, toda terça.

```bash
.venv/Scripts/python.exe inpi/ingest.py --baixar
```

Baixa os 10 CSVs (~2,2 GB) e recria o banco. Sem `--baixar`, carrega o que já estiver em
`inpi/data/raw/`. Leva ~3 min no total.

Pergunte `qual a cobertura da base do INPI?` a qualquer momento. Se a última RPI carregada
tiver mais de 8 dias, a resposta vem com alerta — **resultado vazio de base velha não prova
ausência de anterioridade nem de movimentação.**

## Como se pede

Fale como falaria com um analista. A skill `analista-patentes-inpi` ativa sozinha quando
você menciona patente, reivindicação, anterioridade, INPI, LPI ou claim chart.

```
Busque anterioridades para uma embalagem biodegradável de alginato de sódio
com camada de barreira. Quero cobertura Brasil e Estados Unidos.
```

```
Monte o quadro de confronto da reivindicação 1 do BR 10 2022 010731 2
contra as três anterioridades mais próximas.
```

```
A UFERSA depositou esse pedido em outros países? Traz a família INPADOC.
```

```
Esse pedido cai no art. 10 da LPI? É método terapêutico ou programa em si?
```

```
Qual o andamento do BR 10 2022 010731 2? Traz todos os despachos.
```

```
Quais pedidos a UFERSA depositou em embalagem biodegradável?
```

### Prazos de um cliente, no mundo todo

A carteira é uma entidade persistente, em `inpi/data/carteira.duckdb`. Carregue uma vez,
pergunte quantas vezes quiser.

```
Essa é a carteira da Tecnored: <cole a lista, ou o caminho do XLSX/CSV>
```

```
Levanta sozinho o que a base do INPI conhece da Tecnored, e expande a família.
```

```
Quais os prazos da Tecnored até dezembro? Quero Brasil e exterior, incluindo
os países pequenos.
```

Quatro fontes alimentam a mesma tabela, cada linha carimbada com a origem. Quando
discordam, a divergência **aparece**; não é resolvida por sobrescrita.

| Fonte | O que só ela vê |
| :--- | :--- |
| lista do escritório | a carteira inteira de uma vez, e o número com que cada associado trabalha |
| base do INPI | os casos brasileiros |
| família INPADOC | os equivalentes fora da Europa — AU, CA, CN, IN, ZA… |
| **status legal INPADOC** | **as validações europeias, inclusive nos países do Acordo de Londres** |

A última é a que fechou o buraco. Em **BE, FR, GB, GR, IE, IT, LU, NL e SE** o Acordo de
Londres dispensa a tradução, a validação de um EP não gera publicação nacional e **não
existe membro de família** — 46 de 59 casos de uma carteira real eram invisíveis à busca
por família. Mas o escritório nacional reporta ao EPO o pagamento da anuidade (evento
`PGFP`), e isso está no serviço de status legal.

Medido na família `EP14874476`: dos 15 estados europeus do docketing, o status legal
encontrou **os 15**, os 9 de Londres inclusive — e encontrou **PT com anuidade paga, que o
docketing não tinha**. Também marcou CH e LT como caducados (`PG25`), que por isso ficam
fora da projeção de anuidade.

Toda resposta de `carteira_panorama` traz uma seção **`lacunas`**. Leia antes de tratar o
quadro como completo.

### Controle de carteira e prazos

```
Quais prazos vencem na carteira da Clarke Modet no próximo trimestre?
```

```
Quantas anuidades a Petrobras tem projetadas para 2026?
```

```
Quais casos nossos vencem o prazo do art. 33 (requerimento de exame) este ano?
```

```
O que saiu de novo nos casos da Clarke Modet desde a semana passada?
```

### Mercado e prospecção

```
Qual nossa participação de mercado em polímeros (IPC C08)?
```

```
Quem deposita muito em C08 e não é nosso cliente?
```

```
Qual a regra de manutenção de patente nos EUA? E o prazo de fase nacional
de um PCT com prioridade em 15/01/2024?
```

Peça sempre a **jurisdição**. Se você não disser, o agente pode responder só com os EUA —
e uma busca de anterioridade que ignora Brasil e China está incompleta.

## O que esperar da resposta

Por desenho, o agente:

- **não dá veredito.** Escreve "aparenta estar antecipada por D1, sujeito à confirmação do
  examinador", nunca "não tem novidade". A decisão é ato privativo do INPI (arts. 36 e 37).
- **cita com âncora tripla** — documento + parágrafo/reivindicação + trecho literal entre
  aspas. Sem os três, a célula sai `NÃO LOCALIZADO`.
- **não inventa número de patente.** Só cita o que voltou de uma chamada de ferramenta.
- **declara o que não cobriu.** Se só o USPTO respondeu, ele diz isso.

Um claim chart com **todas** as células preenchidas é sinal de fabricação, não de busca
bem-feita. Célula vazia é resultado normal.

Documento vindo do Lens sai carimbado `[FONTE: Lens.org - token de avaliação, uso
interno]` — não use em entregável de cliente enquanto a assinatura não estiver contratada.

## Testar sem abrir o Claude

```bash
.venv/Scripts/python.exe -m pytest epo inpi -q
```

91 testes. Testam o que quebra em silêncio: achatamento do JSON do EPO, normalização de
número entre as três fontes e de grafia de escritório, tratamento de 401/404/429, a recusa
de ler como prazo ativo um prazo que já foi perdido, e a de tratar como encerrado um
processo cujo indeferimento foi revertido por recurso.

## Estrutura

```
.mcp.json                 fiação dos três servidores
.env                      credenciais (gitignored; modelo em .env.example)
.claude/skills/analista-patentes-inpi/
    SKILL.md              o método de exame
    references/           protocolo anti-alucinação, sintaxe BRS e CQL, claim chart, LPI
epo/                      servidor MCP do EPO OPS + testes
lens/                     desligado — ver "O que está ligado"
inpi/  ingest.py          download e carga dos CSVs do INPI no DuckDB
       inpi_mcp.py        servidor MCP da base brasileira + da carteira
       carteira.py        a carteira do cliente: ingestão, descoberta e panorama
       anuidades.py       projeção sob os arts. 40, 84, 85 e 87 da LPI
       jurisdicoes.py     regras de manutenção no exterior e fase nacional PCT
       escritorios.py     normalização de grafia de escritório
       data/              CSVs e .duckdb (gitignored, ~3,3 GB)
                          carteira.duckdb é banco à parte, de propósito:
                          ingest.py recria inpi.duckdb do zero a cada carga
       referencias/       fontes, prazos observados, apelidos, jurisdições
docs/  capacidades.md     o que o agente responde e o que não
       lgpd.md            decisão sobre dado pessoal em prospecção
vendor/patent_mcp_server/ clone do servidor USPTO (não editar)
docs/aceite/              evidência de que cada fase funciona
```

## Armadilhas já mapeadas

- **USPTO e EPO usam sintaxes de busca incompatíveis.** PPUBS é BRS de sufixo
  (`(termo).ti.`), EPO é CQL (`ti=termo`). Misturar não gera erro, gera resultado errado.
  A docstring da ferramenta do USPTO documenta a sintaxe errada — a correta está em
  `references/busca-ppubs-brs.md`.
- **Texto integral no EPO só existe para EP e WO.** Vazio para um BR significa "o EPO não
  tem o texto", não "o documento não revela o elemento".
- **Família INPADOC é uma invenção só.** BR, US e CN do mesmo depósito contam como **um**
  documento no exame de novidade, não como três anterioridades.
- **Prazo de exigência não é calculado, de propósito.** `dias_citados_no_texto` é leitura
  mecânica e cobre 0,83% dos 5,3 M despachos. Vazio significa "o texto não trouxe número
  inequívoco", não "não há prazo". E **mesmo preenchido não é garantia**: despacho de
  arquivamento cita o prazo que já foi perdido. Leia sempre o texto literal.
- **Anuidade, art. 33, recurso e vigência são projetados** — esses dependem de data-base +
  regra fixa, não de código ambíguo. Mas é **projeção, não fatura**: pagamento em dia não
  gera despacho, então a base não sabe o que já foi pago. Lista de conferência contra o
  docketing, nunca substituto dele.
- **A base do INPI é um dump com data de corte.** Busca vazia numa base de três meses
  atrás não é prova de ausência de anterioridade. Pergunte a cobertura antes de concluir.
- **O ranking de mercado subestima quem assina pelo agente.** O INPI registra o agente
  pessoa física **no lugar** da banca: "Orlando de Souza" tem 11.972 processos e 4 em
  comum com "Clarke Modet". Confira com `inpi_escritorio_resolver` antes de citar
  participação, e mapeie os agentes em `inpi/referencias/escritorios-apelidos.csv`.
- **Troca de escritório não é detectável.** A tabela `procuradores` guarda a representação
  vigente, não a série histórica — só 262 processos em 775 mil têm mais de um escritório.
