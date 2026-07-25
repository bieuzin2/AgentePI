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
`epo`, `lens`). Confira com `/mcp`: os três devem aparecer como *connected*.

**Depois de editar `.mcp.json` ou `.env`, reinicie o Claude Code.** Os servidores sobem
uma vez, no início da sessão.

## O que está ligado

| Servidor | Cobre | Credencial |
| :--- | :--- | :--- |
| `uspto` | patentes e pedidos dos EUA, texto integral, PTAB | nenhuma (PPUBS é público) |
| `epo` | **BR, CN, EP e +100 jurisdições** via INPADOC/DOCDB | `EPO_OPS_KEY` + `EPO_OPS_SECRET` ✅ |
| `lens` | acervo global de patentes; NPL (academia) | `LENS_TOKEN` ⚠️ trial, só Patent API |

Faltando: `USPTO_API_KEY` (destrava dados de andamento e PTAB dos EUA — busca funciona
sem ela) e a camada INPI local, bloqueada em `docs/` até haver um arquivo real da RPI.

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
.venv/Scripts/python.exe -m pytest epo lens -q
```

29 testes, sem rede e sem credencial. Testam o que quebra em silêncio: achatamento do
JSON do EPO, formato de referência, tratamento de 401/404/429.

## Estrutura

```
.mcp.json                 fiação dos três servidores
.env                      credenciais (gitignored; modelo em .env.example)
.claude/skills/analista-patentes-inpi/
    SKILL.md              o método de exame
    references/           protocolo anti-alucinação, sintaxe BRS e CQL, claim chart, LPI
epo/ lens/                servidores MCP + testes
vendor/patent_mcp_server/ clone do servidor USPTO (não editar)
inpi/referencias/         contrato das fontes da RPI
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
