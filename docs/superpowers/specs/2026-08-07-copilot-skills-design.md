# Design — Skills nativas do Copilot Studio pro Agente PI

## Contexto

O Agente PI roteia perguntas para ~38 tools MCP (INPI/EPO/USPTO/BigQuery). As
regras de roteamento (qual tool para qual pergunta) vivem hoje num único campo
de Instruções, num bloco de 15 regras. Três falhas reais de produção têm a
mesma raiz — a regra certa estava lá, mas enterrada e sem saliência:

1. Pergunta de tópico livre + país ("patentes de covid no Nepal") → agente
   escolheu `landscape_*` (BigQuery) sem CPC, consulta de ~64GB.
2. Dossiê de cliente → agente compôs manualmente repetindo `inpi_processo`,
   estourou o timeout de 100s; nunca mostrou o menu de escopo.
3. Perfil de titular (Huawei) → resposta rasa, sem usar `inpi_perfil_titular`.

A Fase H já mitigou (1) e (3) por instrução (regra 9) e por tool nova
(`epo_panorama_topico`), mas o mecanismo — regra enterrada — continua frágil.

**Avaliação das features nativas do Copilot Studio** (pesquisada, não assumida):

- **Skills**: módulos de instrução em markdown (`SKILL.md`: nome + descrição +
  passos), carregados sob demanda quando o nome/descrição casa a intenção,
  podem apontar (soft-pointer) pras tools existentes. **ADOTAR.** É instrução,
  não fonte de dado — não conflita com anti-alucinação — e ataca exatamente a
  falha de roteamento.
- **Conhecimento (Knowledge/RAG)**: síntese generativa sobre documento estático.
  **NÃO.** Conflita com a disciplina "cite fonte+identificador+cobertura"; todo
  dado factual de patente já é (e deve ser) tool — rastreável, vivo. Doc estático
  viraria fonte concorrente e desatualizada.
- **Connected agents**: orquestrador de vários agentes especializados.
  **NÃO agora.** Um agente, um domínio: YAGNI. Adiciona saltos de orquestração =
  latência, onde já batemos no timeout. Revisitar só se existir um 2º agente.
- **Mais tools MCP**: **sob demanda, não é projeto.** Cadência da Fase H
  (adicionar quando uma pergunta real não é respondível) já é o certo.

Conclusão: das quatro, só **Skills** entra agora.

## Objetivo

Tirar o detalhe de roteamento do campo de Instruções e colocá-lo em 3 Skills
sob demanda, uma por rota crítica que já falhou. As Instruções ficam com os
invariantes universais (regras 1-7) + um mapa de roteamento curto.

## Arquitetura: roteador fino sempre-ligado + skills gordas sob demanda

- **Instruções principais** (sempre carregadas): regras 1-7 (anti-alucinação,
  universais) + **mapa de roteamento** — uma linha por rota, apontando pra
  skill. O mapa é a rede de segurança caso o gatilho de uma skill não case.
- **Skills** (carregadas só quando o gatilho casa): os passos detalhados de cada
  rota. O detalhe das antigas regras 8-9 **sai** das instruções e **vai** pras
  skills — move, não duplica (decisão do Gabriel: sem cópia dupla, evita drift).

## As 3 Skills

Cada uma é um `SKILL.md`: frontmatter (nome + descrição-gatilho) + corpo (passos).
Sem scripts — as tools MCP são o "executável", via soft-pointer.

### 1. `busca-topico-pais`
- **Gatilho**: pergunta sobre um TEMA em palavras (não código CPC/IPC) num país
  ou no mundo. Ex: "quantas patentes de covid no Nepal", "baterias de sódio no
  mundo".
- **Passos**: traduzir o tópico PT→EN com sinônimos úteis (covid → "covid OR
  coronavirus OR sars-cov-2"); se ambíguo, perguntar o termo antes de chamar;
  chamar `epo_panorama_topico(termos_ingles, pais)`; NUNCA `landscape_*` (sem CPC
  varre a base, ~64GB); citar `total` real e rotular as agregações como amostra;
  rodapé de fonte EPO.

### 2. `dossie-cliente`
- **Gatilho**: pedido de panorama/dossiê de um cliente. Ex: "panorama do cliente
  X", "como está o portfólio do cliente Y".
- **Passos**: chamar `cliente_dossie` SEM seções → devolve um MENU; MOSTRAR o
  menu ao usuário e perguntar quais seções quer; só então
  `cliente_dossie(secoes=[...])`; avisar que `exterior_epo` consulta o EPO e é
  mais lenta; nunca compor manualmente repetindo `inpi_processo`.

### 3. `perfil-titular`
- **Gatilho**: perfil/portfólio de um titular, cliente OU concorrente. Ex: "qual
  o portfólio da Huawei no Brasil", "perfil da Braskem".
- **Passos**: chamar `inpi_perfil_titular` (já traz evolução por ano, foco
  tecnológico, escritórios); NUNCA repetir `inpi_processo` dezenas de vezes;
  citar contagem grande sempre com a distribuição por ano; tratar
  `cruzamento_bigquery` como aproximação por grafia, nunca oficial;
  `possiveis_relacionados` não somam.

Anuidades/custos NÃO vira skill — é uma linha no mapa de roteamento
(`→ financeiro_projecao`/`inpi_anuidades`, nunca landscape).

## Onde moram e como sobem

- Arquivos versionados em `docs/copilot-skills/<slug>/SKILL.md` (uma subpasta por
  skill, porque o Copilot Studio espera o arquivo nomeado `SKILL.md`; subpastas
  evitam colisão de nome). Slugs: `busca-topico-pais`, `dossie-cliente`,
  `perfil-titular`. Mesmo tratamento de `docs/agente-copilot.md` — fonte de
  verdade no git, reproduzível, revisável.
- As Instruções revisadas (regras 1-7 + mapa) atualizam a seção existente de
  `docs/agente-copilot.md`.
- **Deploy = gate manual via browser** (claude-in-chrome): subir cada `SKILL.md`
  pela aba Skills do Copilot Studio e colar as Instruções revisadas. Mesmo padrão
  da Fase H — nunca automático, o Gabriel confirma antes.

## Riscos e limites

- **Skill não é mágica**: é o mesmo roteador LLM lendo nome+descrição. O ganho é
  saliência (cada intenção com gatilho próprio) + lazy-load (passos fora da briga
  com as outras regras). Por isso a verificação ao vivo é obrigatória, não
  enfeite.
- **Gatilho pode não casar** em fraseado incomum: mitigado pelo mapa de
  roteamento sempre-ligado nas Instruções, que apanha a rota mesmo sem a skill
  carregar.
- **Restrição vigente**: agente NUNCA publicado/compartilhado sem autorização
  explícita do Gabriel. Subir skill é edição no draft, não publicação.

## Verificação ponta a ponta

1. Repetir no painel Visualizar as 3 perguntas que falharam:
   - "Quantas patentes de covid foram depositadas no Nepal?" → usa
     `epo_panorama_topico`, nunca landscape.
   - "Panorama do cliente <X>" → mostra o menu do `cliente_dossie` antes de rodar.
   - "Qual o portfólio da Huawei no Brasil?" → usa `inpi_perfil_titular`, com
     evolução por ano.
2. Confirmar na aba Skills que as 3 skills aparecem e disparam (a reasoning view
   do Copilot mostra a decisão de carregar a skill).
3. Nenhuma pergunta trava em timeout.
