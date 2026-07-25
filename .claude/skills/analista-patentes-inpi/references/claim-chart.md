# Quadro de confronto de reivindicações (claim chart)

## Passo 1 — decompor a reivindicação independente

Toda reivindicação brasileira tem três partes. Separe-as antes de confrontar qualquer coisa:

| Parte | O que é | Peso no exame |
| :--- | :--- | :--- |
| **Preâmbulo** | objeto + características já conhecidas do estado da técnica | Normalmente **não** sustenta novidade |
| **Transição** | a expressão `caracterizado por` | Fronteira formal; tudo antes é admitido como conhecido |
| **Parte caracterizante** | os elementos que o depositante alega serem novos | **É aqui que o exame se decide** |

Numere os elementos da parte caracterizante como `1a`, `1b`, `1c`… Uma linha por elemento.
Reivindicações dependentes entram como linhas próprias (`5 = 1 + limitação X`), nunca
diluídas na independente.

## Passo 2 — montar o quadro

| # | Elemento da reivindicação | D1 — `US 12.618.027 B2` | D2 — `BR 10 2019 000000 0` | Fonte da busca |
| :-- | :--- | :--- | :--- | :--- |
| Pre | Embalagem para alimentos com camada de barreira | ✅ `[0012]` — "a food packaging comprising a barrier layer" | ✅ reiv. 1 — "embalagem alimentícia com camada barreira" | `(packag$ AND barrier).ti.` / ppubs |
| — | *caracterizado por* | — | — | — |
| 1a | Camada externa de PLA com 40–60 µm | ✅ `[0034]` — "outer PLA layer of 45 microns" | ❌ NÃO LOCALIZADO | idem |
| 1b | Agente compatibilizante de origem vegetal | ❌ NÃO LOCALIZADO | ✅ `[0021]` — "compatibilizante derivado de amido" | `(compatibiliz$).clm.` / ppubs |
| 1c | Razão de permeabilidade < 0,3 | ❌ NÃO LOCALIZADO | ❌ NÃO LOCALIZADO | — |

**Uma célula = uma âncora tripla** (documento + localização + trecho literal ≤ 25 palavras).
Sem os três, escreva `NÃO LOCALIZADO`. Ver `protocolo-citacao.md`.

## Passo 3 — ler o quadro

- **Todos os elementos em um único documento** → indício de antecipação sob o art. 11.
  Formule como indício, não como conclusão.
- **Elementos espalhados entre D1 e D2** → questão de art. 13, e aí é obrigatório
  responder: *o que, no próprio D1 ou D2, motivaria o técnico no assunto a combiná-los?*
  Sem resposta ancorada no texto, a combinação não se sustenta.
- **Ao menos um elemento sem revelação em documento algum** → esse elemento é o núcleo
  da defesa do pedido. Aponte-o explicitamente; é a informação mais acionável do relatório.

## Erros que invalidam o quadro

1. Confrontar a reivindicação inteira como bloco, sem decompor — impede identificar qual
   elemento sustenta a patente.
2. Preencher célula por semelhança de tema em vez de revelação literal.
3. Combinar D1+D2 na coluna de **novidade**. Novidade é documento a documento.
4. Ignorar o preâmbulo — o que está antes do `caracterizado por` foi admitido como
   conhecido pelo próprio depositante.
5. Citar título de patente com as tags `<span>` de destaque que o PPUBS devolve.
