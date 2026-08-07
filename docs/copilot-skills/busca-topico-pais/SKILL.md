---
name: Busca de patentes por tópico e país
description: Use quando a pergunta for sobre um TEMA em palavras (não um código CPC/IPC) num país ou no mundo. Ex.: "quantas patentes de covid foram depositadas no Nepal", "patentes sobre baterias de sódio no mundo", "quantas patentes de energia solar no Japão".
---

# Busca de patentes por tópico e país

Quando o usuário pede contagem ou panorama de patentes sobre um tema descrito
em palavras (não uma classificação CPC/IPC) — com ou sem recorte de país:

1. TRADUZA o tópico do português para termos de busca em inglês ANTES de
   chamar a ferramenta. Inclua sinônimos úteis. Ex.: covid →
   `covid OR coronavirus OR "sars-cov-2"`; energia solar →
   `"solar energy" OR photovoltaic`.

2. Se o tópico for AMBÍGUO (pode ter mais de um sentido ou sinônimo relevante),
   PERGUNTE ao usuário qual termo usar antes de chamar. Não adivinhe.

3. Chame `epo_panorama_topico(termos_ingles, pais)` — uma única vez. `pais` é o
   código de 2 letras (NP = Nepal, BR = Brasil) ou vazio para o mundo todo.

4. NUNCA use as ferramentas `landscape_*` (BigQuery) para tópico livre. Elas só
   filtram por prefixo CPC; sem CPC a consulta varre a base inteira e já gerou
   tentativa de ~64GB em produção.

5. Ao responder: cite o campo `total` como o número real do acervo. Rotule as
   agregações (tecnologias, titulares, países, anos) como AMOSTRA quando vier
   `nota_amostra` — são aproximação sobre os documentos analisados, não o
   universo completo. Rodapé de fonte: EPO OPS (DOCDB, 100+ jurisdições).
