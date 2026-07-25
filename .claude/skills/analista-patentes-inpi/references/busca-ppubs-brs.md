# Sintaxe de busca — USPTO (BRS) e EPO OPS (CQL)

Duas bases, duas linguagens de consulta incompatíveis. A parte do USPTO vem primeiro
porque é onde a ferramenta documenta a sintaxe errada; a do EPO está no fim do arquivo.

## USPTO Patent Public Search (BRS)

> ⚠️ **A docstring da ferramenta `ppubs_search_patents` está errada.** Ela documenta
> sintaxe de **prefixo** (`TTL/`, `IN/`, `AN/`, `CPC/`). O PPUBS usa BRS de **sufixo**.
> Ignore a docstring; use este arquivo. Verificado contra a API ao vivo em 2026-07-25.

## O modo de falha que isto evita

Query sem sufixo de campo **não filtra nada** — o PPUBS devolve as concessões mais
recentes (`sort` padrão é `date_publ desc`), com `success: true`. Os números são reais
e conferem no PPUBS. A busca parece ter funcionado e não funcionou.

| Query | O que acontece |
| :--- | :--- |
| `biodegradable AND packaging` | ❌ devolve anticorpos anti-idiotípicos — query ignorada |
| `TTL/biodegradable` | ❌ 0 resultados, sem erro |
| `TTL/"neural network"` | ❌ `INTERNAL_SERVER_ERROR` |
| `(biodegradable AND packaging).ti.` | ✅ embalagem biodegradável |

**Regra:** toda query enviada ao PPUBS termina em um sufixo de campo. Sem sufixo,
descarte o resultado — ele não responde à pergunta.

## Sufixos de campo

| Sufixo | Campo | Exemplo |
| :--- | :--- | :--- |
| `.ti.` | título | `(biodegradable AND packaging).ti.` |
| `.ab.` | resumo | `(molecular AND filtration).ab.` |
| `.clm.` | reivindicações | `(membrane AND selective).clm.` |
| `.spec.` | relatório descritivo | `(chitosan).spec.` |
| `.pn.` | número da publicação | `("6103599").pn.` |
| `.cpc.` | classificação CPC | `(B65D65/46).cpc.` |
| `.ipc.` | classificação IPC | `(C08J5/18).ipc.` |
| `.as.` | titular (assignee) | `("Braskem").as.` |
| `.in.` | inventor | `("Silva").in.` |
| `.pd.` | data de publicação | `(@pd>="20200101").pd.` |

## Operadores

- `AND`, `OR`, `NOT` — booleanos.
- `ADJ` — adjacência (termos vizinhos, na ordem). `(biodegradable ADJ packaging).ab.`
- `ADJn` — até *n* palavras de distância. `(polymer ADJ3 barrier).ab.`
- `SAME` — na mesma sentença.
- `$` — truncamento. `(biodegrad$).ti.` pega biodegradable, biodegradation, biodegrade.
- `" "` — frase exata dentro do parêntese.

## Combinar campos numa query

Cada termo carrega o próprio sufixo, e o conjunto vai entre parênteses:

```
(biodegradable.ti. AND filtration.ab.)
(("Braskem").as. AND (polymer).ti.)
((B65D65/46).cpc. AND (compostable).clm.)
```

## Receita para busca de anterioridade

Nunca uma query só. Rode as três e una os resultados — cada uma erra de um jeito diferente:

1. **Por classificação** — a mais confiável, imune a vocabulário:
   `(B65D65/46).cpc.`
2. **Por termo no título/resumo**, com truncamento para pegar variações:
   `((biodegrad$ ADJ3 packag$)).ab.`
3. **Por reivindicação** — encontra o que o examinador de fato confrontaria:
   `((biodegradable AND barrier AND layer)).clm.`

Depois, para cada candidato relevante, `ppubs_get_patent_by_number` traz o texto
integral para o confronto elemento a elemento.

## Duas armadilhas na leitura da resposta

1. **`total` não é o total real.** O envelope devolve `total == count == limit`. Não
   afirme "foram encontradas N patentes" a partir desse campo — ele conta a página,
   não o acervo.
2. **Títulos vêm com HTML.** O PPUBS injeta destaque:
   `<span term="biodegradable" class="highlight18">Biodegradable</span>`.
   Limpe as tags antes de citar o título em qualquer relatório.

## Sem cobertura fora dos EUA

O PPUBS é só US (USPAT, US-PGPUB, USOCR). Brasil, China, Europa e o resto do mundo
entram pelo EPO OPS (INPADOC/DOCDB), não por aqui. Se a pergunta é sobre BR ou CN e
só o PPUBS respondeu, **a busca está incompleta — diga isso**.

---

# EPO OPS — sintaxe CQL (não é BRS)

> ⚠️ **As duas sintaxes não se misturam.** Mandar BRS de sufixo (`.ti.`) para o EPO ou
> CQL (`ti=`) para o PPUBS não dá erro claro — dá resultado errado. Confira em qual
> ferramenta você está antes de escrever a query.

| CQL (EPO) | Campo | BRS equivalente (PPUBS) |
| :--- | :--- | :--- |
| `ti="biodegradable packaging"` | título | `("biodegradable packaging").ti.` |
| `ab=biodegradable` | resumo | `(biodegradable).ab.` |
| `ta=...` | título **ou** resumo | — |
| `pa="Braskem"` | titular | `("Braskem").as.` |
| `in="Silva"` | inventor | `("Silva").in.` |
| `ipc=/low B65D65/46` | IPC | `(B65D65/46).ipc.` |
| `pn=BR102019000000` | nº publicação | `("...").pn.` |
| `pd within "2020 2026"` | janela de data | `(@pd>="20200101").pd.` |

Operadores: `and`, `or`, `not`. Teto duro de **2000 resultados por consulta** — pedir
além disso retorna erro explícito, e se o total casado passar de 2000 a resposta traz
um aviso de que os resultados são amostra, não acervo.

## Duas armadilhas do EPO

1. **Texto integral quase não existe fora de EP e WO.** `epo_texto_integral` costuma vir
   vazio para BR, US e CN. Vazio aqui significa *"o EPO não tem o texto"*, **não** *"o
   documento não revela o elemento"*. É proibido marcar `NÃO LOCALIZADO` com base nisso —
   busque o texto na base nacional antes.
2. **Membros da mesma família INPADOC são a mesma invenção.** BR, US e CN do mesmo
   depósito contam como **um** documento no confronto de novidade, nunca como três
   anterioridades independentes. Use `epo_familia_inpadoc` para agrupar antes de montar
   o quadro.
