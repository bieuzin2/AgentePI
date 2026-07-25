# O que o agente responde — e o que não responde

Levantado em 2026-07-25 contra as quatro fontes ligadas. Cada item foi classificado
testando de fato, não por suposição.

✅ responde hoje · 🔧 responderia com trabalho definido · ❌ não responde, e não vai

---

## A regra que atravessa tudo

**As bases são registro do passado, não calendário do futuro.**

O INPI publica o que **aconteceu** — pagou, não pagou, foi arquivado. Ele não publica
"vencerá em agosto". Consequência direta: o agente é excelente para responder *"o que
aconteceu com este caso"* e estruturalmente incapaz de responder *"o que vence semana que
vem"* sem uma camada de cálculo construída por cima.

Duas evidências medidas que fecham a questão:

**1. O silêncio é o normal.** Dos 1.864 pedidos da Petrobras na base, só **193 (10%)** têm
qualquer despacho de anuidade. Pagamento em dia **não gera despacho** — o despacho aparece
quando há problema (falta, complementação, extinção). Ausência de despacho de anuidade não
significa "não deve"; significa "nada deu errado, ou ainda não apareceu".

**2. O INPI retifica.** Caso real `PI0803071`, da própria Petrobras:

```
2026-07-14   21.6   "Referente à 18ª anuidade."
2026-07-21   21.8   "Anulada a publicação código 21.6 na RPI 2897 de 14/07/2026"
```

A notificação foi **anulada sete dias depois**. Quem lesse só o primeiro despacho agiria
sobre um ato que deixou de existir. Nenhum sistema que trate o despacho como definitivo
sobrevive a isso — só o despacho seguinte revela.

**Por isso: este agente não é, e não deve virar, o controle de prazos do escritório.** Ele
é a camada de pesquisa, conferência e vigilância. O controle continua sendo do sistema de
docketing e do procurador responsável.

---

## As duas perguntas que motivaram este documento

### *"Quando é a próxima anuidade do caso X?"* — 🔧

Não é consulta, é cálculo. Determinístico e auditável, mas precisa ser construído:

- **Data-base**: `data_deposito` (⚠️ em fase nacional PCT a regra usa o depósito
  internacional — a base traz `numero_pct` e `data_entrada_fase_nacional`).
- **Regra**: art. 84 da LPI — anuidade a partir do início do 3º ano do depósito, nos três
  primeiros meses de cada período anual, com prazo complementar de seis meses mediante
  retribuição adicional (art. 84 § 2º).
- **Teto**: vigência do art. 40. O despacho `16.1` publica isso explicitamente —
  `PI0803071` traz *"Prazo de Validade: 20 (vinte) anos contados a partir de 21/08/2008"*.
- **Estado**: se houve `11.1`, `11.2`, `9.2`, `24.x`, não há mais anuidade a pagar.
- **Última paga**: a base mostra a última anuidade **notificada** (*"Referente à 18ª
  anuidade"*), que é indício forte mas não prova de pagamento.

Diferente do prazo de exigência, isto **não** depende de código de despacho ambíguo — é
data + regra legal fixa. É a única projeção de prazo que eu recomendaria construir. Ainda
assim, saída sempre com a data-base, a regra aplicada e o despacho `16.1` como prova, para
o procurador conferir em 30 segundos.

### *"Quantas anuidades a Petrobras paga em julho de 2026?"* — ❌

Não é respondível, e não é limitação de implementação. A base tem **1 despacho de anuidade
da Petrobras em todo o ano de 2026**. O INPI não publica calendário de vencimento — publica
consequência. Um número respondido aqui seria inventado.

Com a camada de projeção acima, viraria 🔧: *"dos 1.864 pedidos da Petrobras, N estão
vivos e têm anuidade projetada para julho/2026, calculada a partir da data de depósito"* —
com a ressalva de que é projeção, não a conta do INPI.

---

## Caso brasileiro — ciclo de vida completo

### Identificação e titularidade

| Pergunta | Status |
| :--- | :--- |
| Qual o título, resumo, IPC, inventores e titular do BR 10 2022 010731 2? | ✅ |
| Quem é o procurador constituído nesse processo? | ✅ |
| Houve transferência de titularidade? Para quem e quando? | ✅ `25.1` no histórico |
| Esse pedido tem prioridade unionista? De qual país e data? | ✅ tabela `prioridades` |
| É entrada de fase nacional de um PCT? Qual o WO? | ✅ `numero_pct`, `numero_wo` |
| Esse pedido é derivado/dividido de outro? | ✅ tabela `vinculos` |
| O número foi renumerado em algum momento? | ✅ tabela `renumeracoes` |

### Andamento processual

| Pergunta | Status |
| :--- | :--- |
| Qual o andamento completo do processo, despacho a despacho? | ✅ |
| Qual foi o último despacho e em que RPI saiu? | ✅ |
| Esse pedido foi publicado? Quando (art. 30)? | ✅ `3.1` + `data_publicacao` |
| Foi requerido exame? Foi arquivado por falta dele (art. 33)? | ✅ `11.1` |
| Há exigência técnica pendente? Qual o teor? | ✅ `6.x` / `7.1` com texto literal |
| Foi deferido, indeferido ou arquivado? Com que fundamento? | ✅ `9.1` / `9.2` / `11.x` |
| Houve recurso? Qual o resultado? | ✅ `100`, `100.1`, `120`, `121` |
| A patente foi extinta? Por quê? | ✅ `24.x` |
| Qual o prazo de vigência? | ✅ `16.1` traz o texto explícito |
| Esse despacho foi anulado depois? | ✅ `8.8`, `21.8`, `15.x` — **pergunte sempre** |

### Prazos

| Pergunta | Status |
| :--- | :--- |
| Qual o teor e a data da exigência publicada? | ✅ código + RPI + texto literal |
| Quantos dias o próprio despacho declarou? | ✅ quando declarou — cobre 0,83% |
| Qual a data-limite para cumprir esta exigência? | ❌ **por decisão** — ver `prazos-observados.md` |
| Quando vence a próxima anuidade? | 🔧 cálculo art. 84 (acima) |
| Quais casos meus têm prazo vencendo em 30 dias? | ❌ é docketing, não pesquisa |

### Vigilância e inteligência

| Pergunta | Status |
| :--- | :--- |
| Que pedidos a Petrobras/UFERSA depositou? | ✅ 1.864 e 4 respectivamente |
| Quais indeferimentos (`9.2`) saíram na RPI 2898? | ✅ |
| Que pedidos foram publicados esta semana em B65D 65/46? | ✅ `inpi_despachos_por_rpi` + `inpi_busca_ipc` |
| Quem são os maiores depositantes em determinada IPC? | 🔧 agregação simples sobre a base |
| Como evoluiu o depósito nessa tecnologia nos últimos 10 anos? | 🔧 idem |
| Meu concorrente teve pedido arquivado ou indeferido? | ✅ varredura por titular + código |

### Anterioridade

| Pergunta | Status |
| :--- | :--- |
| Existe patente BR sobre embalagem biodegradável de alginato? | ✅ busca em título e resumo |
| E por classificação, independente de vocabulário? | ✅ `inpi_busca_ipc` |
| Monte o quadro de confronto da reivindicação 1 contra D1 e D2 | ⚠️ ver ressalva abaixo |

⚠️ **A base do INPI não tem o quadro reivindicatório** — só título e resumo. Para confronto
elemento a elemento de um documento BR é preciso o PDF do pedido, que não está aqui.
Confronto pleno hoje só com documentos US (PPUBS) e EP/WO (EPO).

---

## Caso no exterior

### O que funciona hoje

| Pergunta | Status |
| :--- | :--- |
| Esse pedido BR tem equivalente em outros países? | ✅ `epo_familia_inpadoc` |
| Em quais jurisdições meu concorrente protegeu essa invenção? | ✅ família INPADOC |
| Qual o andamento do EP correspondente? | ✅ INPADOC legal — 50 eventos num caso testado |
| A patente US caducou por falta de taxa de manutenção? | ✅ evento `LAPS` |
| A taxa de manutenção US foi paga? | ✅ evento `FPAY` |
| Saiu lembrete de manutenção nos EUA? | ✅ evento `REMI` |
| A patente caducou em algum país europeu? | ✅ `VD1` (NL), `LAPSED IN A CONTRACTING STATE` |
| Quais reivindicações do EP? | ✅ `epo_texto_integral` |
| Busca de anterioridade em US full-text | ✅ PPUBS |
| Busca em 100+ jurisdições, inclusive CN | ✅ EPO OPS via DOCDB |

Vale o mesmo aviso do Brasil: `FPAY`, `LAPS` e `REMI` são **registro do que aconteceu**.
O INPADOC não publica "vence em novembro".

### O que está bloqueado por credencial

| Pergunta | Status |
| :--- | :--- |
| Histórico completo de prosecução no USPTO (file wrapper) | 🔧 falta `USPTO_API_KEY` |
| Continuidade, divisionais e CIPs nos EUA | 🔧 idem — `odp_get_continuity` |
| Cadeia de titularidade (assignments) nos EUA | 🔧 idem |
| Há IPR ou PGR contra essa patente no PTAB? | 🔧 idem |

Chave gratuita em `account.uspto.gov/api-manager`, exige verificação por ID.me.

### O que nenhuma fonte aqui dá

| Pergunta | Status |
| :--- | :--- |
| Quanto custa a anuidade em cada país? | ❌ tabela de taxas, fonte separada |
| Quando vence a anuidade EP/US/CN? | ❌ nenhuma fonte publica vencimento futuro |
| Prazo de entrada em fase nacional (30/31 meses) do meu PCT | 🔧 cálculo a partir da prioridade |
| Andamento no CNIPA além do que o INPADOC espelha | ❌ exigiria fonte chinesa direta |
| Literatura não-patentária | ⚠️ Lens, mas o trial só liberou a Patent API |

---

## O que ele nunca vai responder

Não está em base pública nenhuma, e nenhum trabalho de engenharia resolve:

- Prazos internos do escritório, instruções e decisões do cliente
- Petições protocoladas mas ainda não publicadas na RPI
- Se o pagamento foi de fato feito (a base mostra notificação, não quitação)
- Correspondência com o INPI fora do que é publicado
- Estratégia, orçamento, valor da carteira
- **Se o prazo já correu para o seu caso concreto** — isso depende do que foi protocolado,
  de justa causa, de suspensão. É juízo do procurador.

---

## Para virar controle de escritório de fato

Em ordem de valor sobre esforço:

1. **Watchlist de processos** (baixo esforço) — arquivo com os números da carteira; a cada
   reingestão, listar o que mudou desde a última verificação. Resolve *"o que saiu de novo
   nos meus casos"*, que é a pergunta operacional mais frequente.
2. **Projeção de anuidades** (médio) — art. 84 sobre `data_deposito`, com filtro de casos
   vivos e o `16.1` como teto. Entrega *"anuidades projetadas para o mês"* com a conta à
   vista.
3. **Reingestão automática** (baixo) — os CSVs saem todo dia; hoje a carga é manual e a
   data de corte envelhece em silêncio.
4. **Detecção de anulação** (baixo, alto valor) — sinalizar quando um despacho posterior
   anula um anterior. É a armadilha do `PI0803071`.
5. **Tabela de códigos revisada** (alto, requer profissional habilitado) — só então faz
   sentido falar em data-limite de exigência. Insumo de priorização já levantado em
   `inpi/referencias/prazos-observados.md`.

Nada disso muda a regra de ouro: **o agente informa e confere; o controle é do procurador.**
