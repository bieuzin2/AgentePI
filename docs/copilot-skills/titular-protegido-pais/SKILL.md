---
name: titular-protegido-pais
description: >-
  Use quando perguntarem se/onde um titular protegeu invenções num país específico, cruzando com outro país. Ex.: "patentes da Petrobras depositadas em Omã com fase nacional ativa no Brasil", "onde a Huawei tem patente no Golfo", "quais casos do cliente X têm membro no Japão".
---

# Titular protegido num país (cruzando jurisdições)

A pergunta é sempre a mesma forma: um TITULAR + um PAÍS-ALVO (às vezes cruzado com um
segundo país, tipicamente o BR). Não busque o país direto por texto — siga a família.

**Método (não improvise, não pule etapas):**

1. Parta da carteira conhecida do titular, não de uma busca solta:
   - **Membro BR**: `inpi_portfolio_titular(nome)` — resolve o titular pela chave curada e
     lista os processos brasileiros.
   - **Alcance global**: `epo_busca(cql='pa="<titular>"')` — e tente também o nome oficial
     (ex.: Petrobras → `pa="petroleo brasileiro"`), porque o DOCDB indexa a razão social.

2. Para cada caso relevante, expanda a família com `epo_familia_inpadoc(referencia)`. Os
   membros da família são a MESMA invenção em outras jurisdições — é ali que o país-alvo
   aparece, se aparecer.

3. Filtre os membros pelo país-alvo (código de 2 letras). Se cruzar com o BR ("…e que tem
   fase nacional ativa no Brasil"), pegue o membro `BR` da mesma família e confirme o
   andamento com `inpi_processo(numero)` — vivo/arquivado/concedido.

4. **ENQUADRAMENTO OBRIGATÓRIO de cobertura** — este é o ponto que mais gera resposta errada:
   o DOCDB/INPADOC indexa **mal ou nada** várias jurisdições — Golfo (OM Omã, AE, SA, QA, KW,
   BH, o regional GC do GCC), boa parte da África, Ásia Central. Se a busca por membro nesses
   países voltar **zero**, isso é **lacuna da fonte, não prova de ausência**. NUNCA conclua
   "o titular não protegeu lá" a partir de um zero do EPO nesses países.

5. Quando o país-alvo é mal coberto (ex.: Omã), diga isto explicitamente e aponte o que
   destravaria a resposta: o número nacional no país-alvo, o número da publicação lá, o
   PCT/WO, ou o número regional (GCC). Com qualquer um desses, dá para expandir a família
   INPADOC, achar o membro BR e conferir o titular/andamento no INPI.

6. Rodapé de fonte: EPO OPS (DOCDB/INPADOC, 100+ jurisdições) para o exterior; dados abertos
   INPI + `inpi_cobertura` para o membro BR. Nunca misture as duas cadências numa afirmação.
