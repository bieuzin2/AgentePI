# Estrutura do parecer técnico preliminar

Ordem fixa. Cada seção só se abre quando a anterior está fechada — não adianta examinar
novidade de matéria excluída pelo art. 10 nem de relatório insuficiente sob o art. 24.

---

## 1. Identificação e objeto

Número do pedido, data de depósito, prioridade unionista (art. 16) se houver,
classificação IPC/CPC, depositante, e o quadro reivindicatório em exame (nº de
independentes e dependentes).

**A data de corte do estado da técnica é a data de depósito ou de prioridade.** Fixe-a
aqui, explicitamente. Todo documento posterior a ela sai da análise.

## 2. Enquadramento — arts. 10 e 18

Antes de qualquer busca: a matéria é invenção? É patenteável?

Se recair no art. 10 (notadamente programa de computador *em si*, método comercial,
método terapêutico) ou no art. 18, registre e **pare aqui**. Não gaste busca com matéria
fora do sistema. Distinga na fundamentação: art. 10 = não é invenção; art. 18 = é
invenção, mas não se concede.

## 3. Suficiência descritiva — art. 24

O relatório permite a um técnico no assunto realizar o objeto? Reivindicações
fundamentadas no relatório (art. 25)? Insuficiência derruba o pedido sozinha.

## 4. Busca no estado da técnica

Registre, para cada base consultada:

| Base | Ferramenta | Query literal | Nº de candidatos | Cobertura |
| :--- | :--- | :--- | :--- | :--- |
| USPTO | `ppubs_search_patents` | `(biodegrad$ AND packag$).ab.` | 12 | somente US |
| EPO OPS | `epo_busca` | … | 8 | BR, CN, EP, +100 |
| INPI | `inpi_busca` | … | 3 | BR |

Duas obrigações:
- **Queries literais**, reproduzíveis. Busca que não pode ser repetida não pode ser auditada.
- **Declare o que não foi coberto.** Se só o PPUBS respondeu, o parecer cobre os EUA e
  mais nada — diga isso em vez de deixar implícito.

## 5. Confronto — quadro por reivindicação

Um quadro por reivindicação independente. Ver `claim-chart.md`. Cada célula com âncora
tripla ou `NÃO LOCALIZADO`.

## 6. Novidade — art. 11

Documento a documento. Para cada anterioridade, qual reivindicação estaria antecipada e
por quais elementos, com a citação. **Nunca** some elementos de documentos distintos aqui.

## 7. Atividade inventiva — art. 13

Só para o que sobreviveu ao item 6. Três perguntas, nesta ordem:

1. Qual o problema técnico objetivo que a invenção resolve?
2. Qual o documento mais próximo do estado da técnica e qual a diferença concreta?
3. **O que, no próprio estado da técnica, motivaria o técnico no assunto a chegar a essa
   diferença?** Sem resposta ancorada em texto, não há obviedade demonstrada.

Efeito técnico inesperado, se houver, é o argumento mais forte a favor do depositante —
registre-o com a mesma âncora exigida das anterioridades.

## 8. Aplicação industrial — art. 15

Curto. Só se afasta em caso raro; presumir sem examinar também é erro.

## 9. Síntese e encaminhamento

Não é decisão. É mapa do risco, por reivindicação:

| Reivindicação | Situação | Documento crítico | Encaminhamento sugerido |
| :--- | :--- | :--- | :--- |
| 1 | Aparenta antecipada | D1 `[0034]` | Restringir com o elemento 1c, ausente em D1 e D2 |
| 5 | Sem anterioridade localizada | — | Manter |

Fecha com a ressalva obrigatória:

> Parecer técnico preliminar, não vinculante, baseado nas bases e no período de busca
> declarados no item 4. Não constitui decisão de patenteabilidade — ato privativo do INPI
> (arts. 36 e 37 da LPI) — nem substitui a análise do procurador responsável.

---

## Se houver despacho e prazo envolvidos

Prazo nunca vem do parecer. Vem da ferramenta INPI, ancorado na data de publicação da RPI
que veiculou o despacho, e sai acompanhado do texto literal do despacho e da URL da
revista. O parecer apenas reproduz o que a ferramenta devolveu, com a ressalva de que o
controle de prazos é do procurador. Se o código do despacho não estiver na tabela
revisada, o resultado é `PRAZO DESCONHECIDO` — nunca uma estimativa por analogia.
