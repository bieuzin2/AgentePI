---
name: exigencias-escritorio
description: >-
  Use quando perguntarem quantas exigências um escritório cumpriu / respondeu / recebeu num período. Ex.: "quantas exigências a Clarke Modet cumpriu no INPI em 2026", "quantas exigências técnicas nosso escritório respondeu este ano".
---

# Exigências de um escritório num período

⚠️ **LEIA ISTO ANTES DE RESPONDER — é a parte mais importante:** o **cumprimento** de uma
exigência é uma **petição** (serviços 206/207 na GRU), protocolada pelo escritório. Os dados
abertos do INPI **não publicam petições** — só despachos da RPI. **Não existe despacho
"exigência cumprida".** Logo é impossível contar "exigências cumpridas" com esta base.
Qualquer número respondido como "cumpridas" seria inventado. **Comece a resposta por essa
limitação, não a esconda no fim.**

O que a base **permite** medir, e que você deve entregar no lugar:

1. Resolva o escritório com `inpi_escritorio_resolver(nome)`. Confira o bloco `composicao`
   (firma vs agentes afiliados) para poder explicar a carteira, se perguntarem.

2. Chame `inpi_exigencias_escritorio(escritorio, ano)`. Ele devolve, para os processos do
   escritório naquele ano de publicação:
   - `exigencias_emitidas` — exigências que o INPI **publicou** (códigos 6.1 técnica, 2.5
     formal preliminar, 7.1 parecer). É o universo que o escritório teve de responder.
   - `arquivadas_por_nao_cumprimento` — código **11.2** (arquivamento por exigência não
     cumprida, art. 36 §1º). É a **única** afirmação direta do INPI sobre cumprimento, e ela
     é negativa: aqui a exigência **não** foi cumprida.
   - `proxy_cumpridas` — `emitidas − não cumpridas`. É **proxy grosseiro**, não a conta do
     INPI: ignora exigências ainda em aberto e desfechos publicados em outro ano.

3. Ao responder, nesta ordem: (a) a ressalva de que cumprimento é petição não publicada;
   (b) quantas exigências foram **emitidas** no período; (c) quantas **não** foram cumpridas
   (11.2); (d) o `proxy_cumpridas` **rotulado como aproximação**. Repita o campo `aviso` do
   retorno. Rodapé: dados abertos INPI + a cobertura de `inpi_cobertura`.

4. Se pedirem a contagem exata de petições de cumprimento (serviços 206/207), diga que ela
   exige o sistema de docketing/protocolo do escritório ou a base de petições do INPI —
   nenhum dos dois está aqui.
