# Tratamento de dado pessoal — base de patentes do INPI

**Decisão registrada em 2026-07-25.** Este documento existe para que o compliance da
Clarke Modet possa revisar a escolha, não para substituí-la.

---

## Que dado pessoal existe aqui

A base local vem de `dadosabertos.inpi.gov.br`, publicada sob a Portaria INPI/PR nº 70/2022
(Plano de Dados Abertos), licença Creative Commons. É dado público por determinação legal —
o INPI publica seus atos por força da Lei nº 5.648/1970.

Ainda assim, contém dado pessoal:

| Tabela | Campo | Natureza |
| :--- | :--- | :--- |
| `depositantes` | `depositante` | nome de pessoa física quando o titular é PF |
| `depositantes` | `cgccpfdepositante` | **CPF já mascarado pelo INPI** (`****482****`); CNPJ íntegro |
| `depositantes` | `estado`, `pais` | localização |
| `inventores` | `autor`, `estado`, `pais` | inventor é sempre pessoa física |
| `procuradores` | `procurador`, `cgccpfprocurador` | agente da propriedade industrial |

Volume: 2.337.213 registros de inventor e 1.197.157 de depositante.

## A decisão

**Listagens comerciais (prospecção) incluem pessoa física e jurídica**, com rótulo
explícito sempre que houver PF no resultado.

Foi uma escolha do usuário, tomada com a alternativa à vista. A opção mais restritiva
— limitar prospecção a pessoa jurídica — foi apresentada e não adotada.

O rótulo emitido pela ferramenta:

> Esta lista contém PESSOA FÍSICA. O INPI já publica o CPF mascarado, mas nome e endereço
> são dado pessoal: uso comercial exige base legal própria (LGPD art. 7º). Pessoa jurídica
> não tem essa restrição.

### Fundamento

- **Origem**: dado público, publicado por obrigação legal, com licença de reuso.
- **Finalidade**: prospecção comercial de serviços de propriedade industrial — atividade
  em que a condição de depositante é o próprio critério de pertinência.
- **Base legal aplicável**: LGPD art. 7º. Dado tornado manifestamente público pelo titular
  dispensa consentimento (art. 7º § 4º), mas **não** dispensa as demais obrigações —
  finalidade, adequação, necessidade e direitos do titular seguem valendo.
- O art. 7º § 7º é o ponto de atenção: tratamento posterior de dado público exige
  propósito legítimo e preservação dos direitos do titular. Prospecção é legítima;
  enriquecimento com outras bases ou revenda da lista não está coberto por esta decisão.

### Limites que a ferramenta respeita

1. Nenhuma tentativa de desmascarar CPF, cruzar com outras bases ou inferir dado não
   publicado.
2. O rótulo aparece no resultado, não só na documentação — quem recebe a lista vê o aviso.
3. A base é local, sem envio a terceiros. Nenhuma tool de prospecção manda dado para fora.
4. `docs/capacidades.md` declara publicamente o que o agente faz com esses dados.

### O que continua em aberto

- Direito de oposição (art. 18, § 2º): se um titular pedir para sair de listas comerciais,
  não há hoje mecanismo de exclusão. Seria uma lista de bloqueio, e não existe.
- Retenção: a base é recarregada inteira a cada ingestão, sem política de descarte.
- Não houve avaliação formal de legítimo interesse (LIA) nem consulta ao DPO.

Se o compliance decidir restringir, a mudança é pequena: filtrar
`tipopessoadepositante = 'pessoa jurídica'` nas tools de prospecção.

## Onde isso está no código

- `inpi/inpi_mcp.py` → `_AVISO_PESSOAL`, aplicado em `inpi_prospeccao`.
- Consulta de processo individual (`inpi_processo`) mostra PF sem rótulo: é consulta
  processual, não listagem comercial, e o dado é o mesmo que a RPI publica.

## Alertas por e-mail (vigilância autônoma, Fase 1)

Os alertas gerados por `vigilancia/vigias.py` e enviados por `vigilancia/email_alerta.py`
trazem apenas número de processo, código/texto de despacho público e status legal — nunca
nome de pessoa física de depositante ou inventor. Decisão deliberada: o e-mail sai do
ambiente controlado do escritório para a caixa de entrada do Gmail, então o corte é mais
conservador do que nas tools de consulta interna.
