# Copilot Studio Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mover o roteamento de tool das Instruções monolíticas do Agente PI para 3 Skills nativas do Copilot Studio, uma por rota que já falhou em produção.

**Architecture:** Roteador fino sempre-ligado (regras 1-7 anti-alucinação + mapa curto nas Instruções) + 3 Skills gordas carregadas sob demanda (`SKILL.md` versionados no repo). O detalhe das antigas regras 8-9 sai das Instruções e vai pras Skills — move, não duplica. Deploy por gate manual via browser.

**Tech Stack:** Markdown (`SKILL.md` = fonte de verdade no git); Copilot Studio (aba Skills + campo Instruções); claude-in-chrome pro deploy.

## Global Constraints

- Anti-alucinação: nada factual fora do retorno de tool MCP. Skill é instrução, nunca fonte de dado.
- Sem duplicar detalhe: passos de roteamento vivem SÓ nas Skills; Instruções ficam com regras 1-7 + mapa curto.
- Agente NUNCA publicado/compartilhado sem autorização explícita do Gabriel. Subir skill = edição no draft, não publicação.
- Deploy via browser é GATE MANUAL: a última task PARA e espera confirmação do usuário antes de tocar o Copilot Studio.
- Spec de referência: `docs/superpowers/specs/2026-08-07-copilot-skills-design.md`.

---

### Task 1: Criar os 3 arquivos SKILL.md versionados

**Files:**
- Create: `docs/copilot-skills/busca-topico-pais/SKILL.md`
- Create: `docs/copilot-skills/dossie-cliente/SKILL.md`
- Create: `docs/copilot-skills/perfil-titular/SKILL.md`

**Interfaces:**
- Consumes: nada (arquivos novos).
- Produces: 3 skills com slugs `busca-topico-pais`, `dossie-cliente`, `perfil-titular`, referenciadas pelo mapa de roteamento da Task 2 e subidas na Task 3. Cada uma aponta (soft-pointer) pras tools MCP: `epo_panorama_topico`, `cliente_dossie`, `inpi_perfil_titular`.

- [ ] **Step 1: Criar `docs/copilot-skills/busca-topico-pais/SKILL.md`**

```markdown
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
```

- [ ] **Step 2: Criar `docs/copilot-skills/dossie-cliente/SKILL.md`**

```markdown
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
```

- [ ] **Step 3: Criar `docs/copilot-skills/perfil-titular/SKILL.md`**

```markdown
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
```

- [ ] **Step 4: Verificar que os 3 arquivos existem e citam a tool certa**

Run: `ls docs/copilot-skills/*/SKILL.md && grep -l epo_panorama_topico docs/copilot-skills/busca-topico-pais/SKILL.md && grep -l cliente_dossie docs/copilot-skills/dossie-cliente/SKILL.md && grep -l inpi_perfil_titular docs/copilot-skills/perfil-titular/SKILL.md`
Expected: lista os 3 arquivos e cada grep casa (retorna o path).

- [ ] **Step 5: Commit**

```bash
git add docs/copilot-skills/
git commit -m "docs(skills): 3 SKILL.md versionados para o Copilot Studio"
```

---

### Task 2: Revisar as Instruções (regras 1-7 + mapa de roteamento)

**Files:**
- Modify: `docs/agente-copilot.md` (bloco de instruções entre as cercas ``` da seção "Instruções do agente")

**Interfaces:**
- Consumes: os 3 slugs de skill da Task 1.
- Produces: texto de Instruções revisado, pronto pra colar no Copilot Studio na Task 3.

**Contexto:** Hoje o bloco tem regras 1-8 + regra 9 (roteamento). As regras 8 e 9 carregam o DETALHE de qual tool usar — esse detalhe agora vive nas Skills. Substituir as regras 8 e 9 por um único bloco "MAPA DE ROTEAMENTO" curto. Regras 1-7 ficam intactas. O parágrafo "O que você cobre (exemplos...)" fica intacto.

- [ ] **Step 1: Ler o arquivo pra localizar as regras 8 e 9 atuais**

Run: `grep -n "USE A FERRAMENTA CERTA\|ROTEAMENTO POR TIPO\|O que você cobre" docs/agente-copilot.md`
Expected: mostra as linhas de início da regra 8, da regra 9 e do parágrafo de exemplos.

- [ ] **Step 2: Substituir as regras 8 e 9 pelo mapa de roteamento**

Apagar todo o texto da regra 8 (`8. USE A FERRAMENTA CERTA...`) e da regra 9 (`9. ROTEAMENTO POR TIPO...` até o fim da regra 15/`~64GB em produção.`), e no lugar colocar exatamente:

```
8. MAPA DE ROTEAMENTO — escolha a ferramenta pelo TIPO de pergunta, não por
   familiaridade. Para os casos abaixo, existe uma Skill dedicada com os passos
   detalhados; siga a Skill. O mapa é a rede de segurança caso a Skill não
   dispare:
   - Tópico livre (tema em palavras, não código CPC/IPC) + país ou mundo →
     Skill "Busca de patentes por tópico e país" (usa epo_panorama_topico).
     NUNCA landscape_* para tópico livre.
   - Panorama/dossiê de um cliente → Skill "Dossiê de cliente" (usa
     cliente_dossie sem seções primeiro, mostra o menu, só então roda).
   - Perfil/portfólio de um titular (cliente ou concorrente) → Skill "Perfil
     analítico de titular" (usa inpi_perfil_titular, nunca compõe na mão).
   - Anuidades/custos de um cliente → financeiro_projecao ou inpi_anuidades.
     NUNCA landscape_* para isso.
   - landscape_* (BigQuery) SÓ quando a pergunta já vier com classificação
     CPC/IPC conhecida, ou pedir ranking mundial por tecnologia classificada.
```

- [ ] **Step 3: Verificar que o detalhe saiu e o mapa entrou**

Run: `grep -c "MAPA DE ROTEAMENTO" docs/agente-copilot.md && grep -c "TÓPICO LIVRE (palavra/tema" docs/agente-copilot.md`
Expected: primeiro = `1` (mapa entrou); segundo = `0` (o texto detalhado antigo da regra 9 saiu).

- [ ] **Step 4: Commit**

```bash
git add docs/agente-copilot.md
git commit -m "docs(agente): move detalhe de roteamento para Skills, deixa mapa curto"
```

---

### Task 3: Deploy no Copilot Studio (GATE MANUAL via browser)

**Files:** nenhum no repo — ação no Copilot Studio ao vivo.

**Interfaces:**
- Consumes: os 3 `SKILL.md` (Task 1) e o texto de Instruções revisado (Task 2).
- Produces: agente com as 3 skills ativas e as instruções atualizadas no draft.

- [ ] **Step 1: PARAR e pedir confirmação**

Não abrir o browser automaticamente. Enviar ao usuário: "Tasks 1 e 2 commitadas. Pronto pro deploy no Copilot Studio (subir 3 skills + colar instruções revisadas). Confirma que quer que eu abra o browser agora?" Esperar o "sim".

- [ ] **Step 2: Abrir o agente e criar as 3 Skills**

Via claude-in-chrome, no agente "Agente PI" (ID `ada5b553-aa4f-4ff1-bd9c-8eccea04992b`), aba de edição (Criar), seção Skills → "+". Para cada skill, usar "create from blank" e colar `name`, `description` e o corpo de instruções do respectivo `SKILL.md`. Repetir para as 3.

- [ ] **Step 3: Colar as Instruções revisadas**

No campo Instruções, selecionar tudo (ctrl+a) e digitar o texto revisado (regras 1-7 + mapa de roteamento da Task 2 + o parágrafo de exemplos que permanece). Salvar (ícone de disquete). Confirmar persistência recarregando a página e conferindo com screenshot.

- [ ] **Step 4: Verificação ao vivo no painel Visualizar**

Rodar as 3 perguntas que falharam e confirmar o roteamento:
- "Quantas patentes de covid foram depositadas no Nepal?" → usa `epo_panorama_topico`, nunca landscape.
- "Panorama do cliente Tecnored" → mostra o menu do `cliente_dossie` antes de rodar.
- "Qual o portfólio da Huawei no Brasil?" → usa `inpi_perfil_titular` com evolução por ano.

Confirmar na reasoning view que a skill correspondente foi carregada. Nenhuma pergunta pode travar em timeout. Fechar a aba do browser ao final.

- [ ] **Step 5: Atualizar memória**

Registrar em `C:\Users\Gabriel\.claude\projects\C--Users-Gabriel-Desktop-Patentes\memory\plano-copilot365-metricas.md` que as 3 skills foram criadas e verificadas ao vivo, e o resultado da verificação.

---

## Notas de execução

- Tasks 1 e 2 são só markdown — sem suíte de teste; a verificação é grep + revisão de conteúdo.
- Task 3 é a única com efeito externo e é gate manual por decisão do Gabriel.
- Se o "create from blank" da aba Skills tiver campos diferentes de name/description/instructions, adaptar na hora — o conteúdo dos `SKILL.md` é a fonte de verdade e cabe em qualquer um dos dois modos (blank ou upload de arquivo).
