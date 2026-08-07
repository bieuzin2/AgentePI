---
name: Perfil analítico de titular
description: Use quando a pergunta for sobre o perfil ou portfólio de um titular, seja cliente OU concorrente. Ex.: "qual o portfólio da Huawei no Brasil", "perfil da Braskem", "como evoluíram os depósitos da Petrobras".
---

# Perfil analítico de titular

Quando o usuário pede o perfil/portfólio de um titular (cliente ou concorrente):

1. Chame `inpi_perfil_titular`. Ele já traz evolução de depósitos por ano, foco
   tecnológico (subclasses IPC) e escritórios que representam — incluindo os
   principais nos últimos anos, para ver troca de banca.

2. NUNCA repita `inpi_processo` dezenas de vezes para montar isso na mão. A
   ferramenta composta é o caminho certo.

3. Ao citar uma contagem grande, acompanhe SEMPRE da distribuição por ano que a
   sustenta — o número seco sozinho não é citável. Note que `total_processos_br`
   inclui os `sem_data_de_deposito`, que não aparecem na evolução por ano.

4. Se vier `cruzamento_bigquery`, trate como APROXIMAÇÃO de ordem de grandeza
   (pode divergir por grafia do titular entre as bases), nunca como número
   oficial.

5. `possiveis_relacionados` NÃO somam na contagem — mencione apenas como "podem
   ser relevantes, não incluídos".
