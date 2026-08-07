---
name: Dossiê de cliente
description: Use quando o usuário pedir um panorama ou dossiê de um cliente. Ex.: "panorama do cliente X", "como está o portfólio do cliente Y", "faz um dossiê da Tecnored".
---

# Dossiê de cliente

Quando o usuário pede o panorama/dossiê de um cliente:

1. Chame `cliente_dossie` SEM o parâmetro `secoes`. Nessa forma ele devolve
   apenas um MENU (custo ~zero), não roda nenhuma consulta pesada.

2. MOSTRE o menu ao usuário e pergunte quais seções ele quer. Não decida
   sozinho. As seções são: processos_e_anuidades, saude, exterior_epo.

3. Só depois da escolha, chame `cliente_dossie(secoes=[...])` com as seções
   pedidas. Avise que a seção `exterior_epo` consulta o EPO e é mais lenta —
   confirme antes de incluí-la.

4. NUNCA componha o dossiê na mão repetindo `inpi_processo` dezenas de vezes —
   isso estoura o timeout de 100s do Copilot Studio. A ferramenta composta já
   faz o trabalho.
