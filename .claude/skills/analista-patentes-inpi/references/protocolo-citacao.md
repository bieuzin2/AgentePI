# Protocolo de citação e verificação

Estas sete regras são o núcleo da skill. Elas existem porque o modo de falha de um LLM
em análise de patentes não é errar visivelmente — é produzir um parecer bem formatado,
com números de patente plausíveis e trechos convincentes que não existem no documento.

## 1. Proibido veredito

O agente emite **parecer técnico preliminar, não vinculante**. Nunca escreve
"indeferido", "deferido", "patenteável" ou "nulo".

- ❌ "A reivindicação 1 não possui novidade."
- ✅ "A reivindicação 1 aparenta estar antecipada por D1; sujeito à confirmação do examinador."

A decisão de patenteabilidade é ato administrativo privativo do INPI (arts. 36 e 37 da
LPI). O agente organiza a prova; quem conclui é o profissional responsável.

## 2. Âncora tripla obrigatória

Toda afirmação de que um documento revela um elemento exige, **na mesma célula**:

1. **Identificador** do documento (`US 12.618.027 B2`)
2. **Localização precisa** — parágrafo `[0034]`, reivindicação 7, coluna 5 linha 12, figura 3
3. **Trecho literal transcrito**, ≤ 25 palavras, entre aspas

Sem os três, a afirmação não entra.

## 3. Sem âncora → `NÃO LOCALIZADO`

Proibido inferir revelação a partir de título, resumo ou classificação IPC/CPC.

> "O documento é classificado em B65D65/46, então provavelmente descreve o revestimento."

Isso é dedução, não revelação. Célula vazia é **resultado válido e frequente**. Um claim
chart com todas as células preenchidas é sinal de fabricação, não de busca bem-feita.

## 4. Nenhum identificador sem chamada de ferramenta

Proibido citar número de patente que não retornou de uma chamada de ferramenta **nesta
sessão**. Nada de "US 9.123.456 provavelmente descreve...". Número não recuperado é
número inventado.

Se nenhuma ferramenta de busca estiver conectada no ambiente, declare isso e **não
prossiga** para o exame de novidade.

## 5. Coluna de proveniência

Todo quadro de confronto carrega, por linha, **qual ferramenta e qual query** produziram
o documento. Em PI a rastreabilidade da fonte é o produto — um parecer cuja busca não
pode ser reproduzida não pode ser auditado.

## 6. Separar os três eixos — não misturar

| Eixo | Base legal | Regra de confronto |
| :--- | :--- | :--- |
| **Novidade** | Art. 11 | Contra **um único** documento por vez. Combinar documentos aqui é erro. |
| **Atividade inventiva** | Art. 13 | Combinação permitida, mas exige **motivação demonstrada** |
| **Aplicação industrial** | Art. 15 | Eixo independente; raramente decisivo, mas nunca presumido |

Sobre atividade inventiva: proibido escrever "seria óbvio combinar D1+D2" sem apontar,
**no próprio estado da técnica**, o que motivaria o técnico no assunto a fazer essa
combinação. Combinação retrospectiva (*hindsight*) — montar o quebra-cabeça já sabendo a
figura — é o erro mais comum de parecer gerado por LLM e o mais fácil de derrubar em
recurso.

## 7. Auto-verificação antes de entregar

Antes de fechar o relatório, releia **cada trecho citado** e confirme que ele aparece
literalmente no documento recuperado. Trecho não confirmado → remova a linha inteira,
não a reescreva.

---

## Restrição de fonte durante o trial do Lens.org

Enquanto a assinatura do Lens.org não estiver contratada, o token é de avaliação e os
termos vedam uso comercial do output. Documento cuja **única** origem é o Lens não entra
em entregável destinado a cliente ou a processo faturado. Pode ser usado para pesquisa
interna e para a decisão de compra. Toda saída dessa fonte vem carimbada
`[FONTE: Lens.org — token de avaliação, uso interno]` — se o carimbo está lá, o documento
é de uso interno.
