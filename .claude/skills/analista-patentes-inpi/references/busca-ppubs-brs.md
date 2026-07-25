# Sintaxe de busca — USPTO Patent Public Search (BRS)

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
