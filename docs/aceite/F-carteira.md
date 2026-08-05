# F0–F6 — a carteira como entidade

Status: ✅ **aprovado ao vivo contra a API do EPO em 2026-07-27**

O que motivou: o agente só respondia sobre prazos depois que o operador mandava o
docketing. A pergunta do negócio — *"quais os prazos do cliente X?"* — não tinha resposta,
e os países pequenos ficavam de fora.

---

## A descoberta que mudou o desenho

O projeto afirmava, em três lugares (`inpi/carteira_manual.py:1-8`, `docs/capacidades.md`,
`README.md`), que a validação de uma patente europeia em BE, FR, GB, GR, IE, IT, LU, NL e
SE era **invisível a qualquer busca**, porque o Acordo de Londres dispensa a tradução, a
validação não gera publicação nacional e portanto não existe membro de família INPADOC.

A afirmação estava **certa sobre a busca de família e errada como afirmação geral.**

O escritório nacional **reporta ao EPO** o pagamento da anuidade. O evento (`PGFP`) está no
serviço de **status legal** do OPS — outro endpoint, que o projeto não usava. Dos sete
serviços disponíveis na lib (`published-data`, `search`, `family`, `legal`, `register`,
`number-service`, `images`), o projeto usava três.

### Medição contra o docketing real — família `EP14874476`

| | |
| :--- | :--- |
| estados europeus na lista do escritório | 15 |
| encontrados pelo status legal (`PGFP`) | **15** — os 9 de Londres inclusive |
| encontrados que a lista **não** tinha | **1 — PT, com anuidade paga** |
| marcados caducados (`PG25`) | CH, LT |
| na lista e não encontrados | AU, CA, CN, IN, UA, ZA — não são EP; vêm pela família |

Duas ressalvas que continuam valendo:

- `PGFP` é afirmação do escritório nacional. `REG` sozinho só diz que **houve ato** no país,
  e o código nacional pode ser de extinção (em CH, `PL` é lapso). Não vão com o mesmo rótulo.
- Ausência de evento **não** prova ausência de validação — pode ser atraso do escritório em
  reportar ao EPO.

---

## Critérios de aceite

| # | Critério | Resultado |
| :-- | :--- | :--- |
| 1 | A mesma carteira entra por CSV, XLSX e lista colada, e converge | ✅ os três produzem os mesmos 59 casos |
| 2 | Ingestão nunca engole coluna nem linha | ✅ coluna e linha recusada voltam nomeadas, com `aviso` |
| 3 | Conflito entre fontes aparece, não é sobrescrito | ✅ `fonte` na chave primária; `conflitos` na saída |
| 4 | Menção de concessão do Register bate com o docketing | ✅ EP3088824 → 2018-11-28; EP3235912 → 2023-12-27 |
| 5 | Data de depósito do Register bate com o docketing | ✅ 2014-12-22 e 2015-11-09 |
| 6 | Os 9 estados de Londres entram na carteira sem lista | ✅ via `PGFP` |
| 7 | A pergunta-mãe responde | ✅ `carteira_panorama('tecnored', …)` → 66 prazos em 29 jurisdições |
| 8 | Caducado não vira prazo a pagar | ✅ 4 casos `PG25` fora do quadro, com lacuna declarada |
| 9 | A seção de lacunas nunca vem vazia por conveniência | ✅ 6 lacunas na execução real |
| 10 | Suite não regride | ✅ 91 → 123 → 132 testes |

---

## Quatro bugs que só apareceram contra a API real

1. **`epo_texto_integral` nunca extraía `description` nem `abstract`.** Ambos caíam no
   `else: texto = ""` e voltavam só como `bruto_json` (`epo/epo_mcp.py:434-435`). Vazio ali
   é lido como "o documento não revela nada" — exatamente a conclusão que o protocolo de
   citação proíbe.
2. **O Register prefixa todas as chaves com `reg:`.** A extração casava `kind`/`date`
   literais e voltava `mencao_de_concessao: None` num EP que tem B1. Passou a comparar por
   sufixo, o que cobre Register e published-data sem um ramo por serviço.
3. **`estados_designados` não é lista de candidatos.** Ao vivo, todo EP devolve ~39 estados
   — desde 2009 o depósito designa todos os contratantes de uma vez. Emitir um candidato
   por estado inventaria 39 casos por patente.
4. **Número canadense também tem 7 dígitos.** Aceitar qualquer número de 7 dígitos como
   publicação EP fazia o Register ser consultado com `CA 3282304`. Passou a exigir
   `tipo='EP-nac'`.

E um de reconciliação: a lista numera a validação pelo **pedido** europeu (`ES 15868739`) e
o INPADOC pela **publicação** (`ES 3235912`). Casar só pelo número duplicava a mesma
validação; dentro de `EP-nac`, a chave passou a ser (estado, família).

---

## Decisões registradas

- **Lens cortado.** O trial só liberou a Patent API, que o EPO OPS já cobre de graça com
  dado oficial. O diferencial seria a Scholarly API (NPL), que devolveu 401. Código
  preservado em `lens/`, desligado no `.mcp.json` — a decisão é reversível.
- **A trava de jurisdição rotula, não bloqueia** (`jurisdicoes.rotulo`). Bloquear faria a
  linha sumir do quadro, e caso que some é pior que caso com ressalva: o operador não
  confere o que não vê. Antes a trava só era consultada por `descrever()`, enquanto os dois
  caminhos que de fato produzem a carteira a ignoravam.
- **Banco separado** (`inpi/data/carteira.duckdb`). `inpi/ingest.py:300` recria
  `inpi.duckdb` do zero a cada carga; a carteira lá dentro seria destruída em silêncio.

---

## Pendências

- **Assinar as jurisdições.** Só o Brasil projeta com rótulo `calculado`. A fila ordenada
  pela carteira real aponta o alvo: **`EP-nac`, 30 dos 59 casos** — assinar essa única linha
  converte metade da carteira. Use `carteira_jurisdicoes_a_revisar`.
- **Buraco estrutural na tabela de regras:** BE, FR, GR, IE, IT, LU, NL e SE não têm linha
  nacional — justamente os estados de Londres. E `EP-nac` é uma linha genérica
  (`primeira=3`) enquanto a linha `GB` do mesmo CSV diz `primeira=5`.
- **`USPTO_API_KEY`** continua ausente: sem ela não há file wrapper, continuidade nem PTAB.
- **Prazos processuais do exterior** (F4) leem o status legal, mas só projetam data para
  jurisdição assinada — hoje, nenhuma.
