# Prazos observados por código de despacho — levantamento empírico

Extraído da base local em 2026-07-25: 5.299.759 despachos, RPI 694 (1972) a 2898
(21/07/2026). Não é tabela oficial: é o que o **próprio INPI escreveu** no campo
`complemento_despacho`, contado.

> ⚠️ **Este arquivo é insumo, não fonte.** Nenhum número aqui deve ser usado para contar
> prazo sem revisão de profissional habilitado. Ver §4.

---

## 1. Por que não existe cálculo automático de prazo

Quatro medições, nesta ordem:

| Medição | Resultado |
| :--- | :--- |
| Despachos que declaram "N (por extenso) dias" | 54.277 de 5.299.759 (**1,02%**) |
| Desses, falsos positivos (prazo já perdido ou ambíguo) | 10.369 (**19,1%**) |
| Cobertura após filtro conservador | 43.908 (**0,83%**) |
| Códigos distintos na base | **432** |

O falso positivo mais grave, texto real do código `11.2`:

> *"**Arquivo o pedido** de patente de invenção, conforme o disposto no art. 36 § 1° da
> LPI, em face da não apresentação de cumprimento da exigência notificada na RPI n° 2596
> de 06/10/2020 **em até 90 (noventa) dias**."*

O "90 dias" é o prazo **que foi perdido e causou o arquivamento**. Lido como prazo a
correr, diria que há três meses para agir sobre um pedido morto.

## 2. Códigos com prazo consistente — candidatos à tabela revisada

Prazo único observado, ordenado por confiabilidade (`% declara` = proporção das
ocorrências do código em que o INPI escreveu o número):

| Código | Prazo | Casos | % declara | Confiança |
| :--- | ---: | ---: | ---: | :--- |
| `205` | 60 d | 2.163 | 99% | alta |
| `100.1` | 60 d | 1.125 | 97% | alta |
| `15.34` | 60 d | 90 | 100% | alta (amostra pequena) |
| `140` | vários | 479 | 89% | ⚠️ 45 valores distintos |
| `100` | 60 d | 5.976 | 87% | alta |
| `121` | 60 d | 4.138 | 68% | boa |
| `23.4` | 90 d | 160 | 64% | boa |
| `15.22.1` | 60 d | 491 | 56% | média |
| `1.5` | 60 d | 8.106 | 36% | média |
| `2.5` | **30 d** | 16.150 | 21% | média — mas 16 mil casos, todos 30 d |
| `11.6.1` | 60 d | 319 | 16% | baixa |
| `28.21` | 60 d | 144 | 11% | baixa |
| `6.20` | 60 d | 631 | 3% | baixa |

**Armadilha de amostragem.** O código `1.3` aparece como "sempre 60 dias" — mas são
**105 casos em 466.158 ocorrências (0,02%)**. São exceções pontuais, não a regra do
código. Concluir "1.3 = 60 dias" a partir disso seria erro grave. Sempre leia a coluna
`% declara` antes da coluna `prazo`.

## 3. Códigos em que o prazo varia por caso — não cabem em tabela

| Código | Valores distintos | O que parece ser |
| :--- | ---: | :--- |
| `15.22` | **66** | devolução/restituição de prazo — o número é específico do caso |
| `140` | 45 | idem |
| `22.12` | 3 (5 d, 10 d, 30 d) | varia por tipo de ato |
| `120` | 2 (60 d, 90 d) | ciência de parecer, varia |
| `6.7` | 2 (60 d, 90 d) | exigência, varia |

Exemplo do `15.22`: *"Reconhecida a justa causa, concedido o prazo de 46 (quarenta e seis)
dias"* — o número vem do cálculo do caso concreto. Nenhuma tabela captura isso.

## 4. Se um dia se quiser cálculo de prazo

O caminho é o do plano original, e **não** a derivação automática desta tabela:

1. `inpi/referencias/codigos_despacho.csv` com `codigo, descricao, prazo_dias, base_legal,
   tipo_contagem, revisado_por, revisado_em`.
2. Preenchido a partir da **tabela oficial de códigos de despacho do INPI**, não daqui.
   Este levantamento serve só para priorizar quais códigos revisar primeiro e para
   conferir se a tabela oficial bate com a prática publicada.
3. Revisado e assinado por agente de PI ou advogado. Alterar prazo = editar CSV, não
   fazer deploy.
4. Código ausente da tabela → `PRAZO DESCONHECIDO` com o texto literal. **Nunca** chutar
   por analogia com código vizinho.
5. Alerta conservador: sinalizar a partir de 50% do prazo decorrido, não na véspera.

Enquanto isso não existir, `dias_citados_no_texto` é leitura mecânica e o texto literal
manda.

## 5. Códigos frequentes e o que o texto revela

Os 432 códigos não estão documentados aqui. Amostra dos mais volumosos, com o que o
próprio `complemento_despacho` deixa ler — **confira na tabela oficial antes de usar**:

| Código | Ocorrências | Indício no texto |
| :--- | ---: | :--- |
| `1.3` | 466.158 | publicação automática (Comunicado RPI 2542) |
| `2.1` | 371.197 | exame formal / prioridade interna |
| `3.1` | 360.942 | publicação do pedido |
| `1.1` | 336.442 | protocolo de depósito |
| `9.1` | 301.246 | carta-patente / concessão |
| `16.1` | 283.557 | vigência ("10 (dez) anos contados a partir de…") |
| `8.6` | 221.541 | anuidade |
| `6.1` | 192.919 | exigência técnica — *"Falta de Clareza das Reivindicações (Art. 25)"* |
| `7.1` | 157.403 | parecer — *"reivindicações … não atendem ao artigo 25 da LPI"* |
| `11.1` | 156.260 | arquivamento — exame não requerido, **art. 33** |
| `9.2` | 92.207 | indeferimento — *"Indefiro o pedido de acordo com o(s) artigo(s) 9º, 14 e 11"* |
| `2.5` | 75.431 | exigência formal preliminar — 30 dias |
| `11.2` | 71.425 | arquivamento — exigência não cumprida, **art. 36 § 1º** |
| `25.1` | 77.370 | transferência de titularidade |
| `24.10` | 69.484 | extinção |
| `100` / `120` / `121` | ~17.000 | recursos e cumprimento de exigência em recurso |
| `28.x` | — | trâmite prioritário |

Dois prazos da LPI que o próprio texto dos despachos confirma:
- **Art. 36 § 1º — 90 dias** para cumprir exigência técnica (visto no `11.2`).
- **Art. 33** — requerimento de exame, cujo descumprimento gera o `11.1`.
