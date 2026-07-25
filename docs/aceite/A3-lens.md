# Aceite A3 — Lens.org

**Data:** 2026-07-25 · **Servidor:** `lens/lens_mcp.py`, FastMCP + `httpx`
**Licença:** token de **avaliação**. Termos v2026.06.01 vedam uso comercial do output.

---

## 🔴 O trial não cobre o produto que justificaria a compra

| Endpoint | Status | Resultado |
| :--- | :--- | :--- |
| `POST api.lens.org/patent/search` | **200** | 1.027.964 documentos para `title: "biodegradable packaging"` |
| `POST api.lens.org/scholarly/search` | **401** | `Unable to authorize user to this resource` |

Patent API e Scholarly API são **assinaturas separadas**. O token concedido cobre só a
primeira.

**Por que isso importa mais que um detalhe de credencial.** O plano estabeleceu que o
único ganho real do Lens sobre EPO+USPTO é a **literatura não-patentária** — artigo,
tese, anais, que o art. 11 da LPI trata como estado da técnica ("por descrição escrita ou
oral, por uso ou qualquer outro meio") e que nenhuma base de patente indexa bem. Patente
o EPO OPS já cobre de graça, com dado oficial e família INPADOC.

Ou seja: **o trial, como está, testa exatamente aquilo que não precisamos comprar.** Sem
acesso à Scholarly API, o critério de decisão do A3 (quantas anterioridades de NPL o Lens
revela que as fontes gratuitas não revelaram) não pode ser medido, e assinar seria
decidir no escuro.

**Ação:** pedir acesso à Scholarly API em
https://www.lens.org/lens/user/subscriptions#access. O relógio de 14 dias corre —
se o acesso não sair a tempo, a recomendação é **não assinar** e reavaliar depois.

## O que ficou pronto

2 tools. `lens_busca_npl` (Scholarly) e `lens_busca_patente` (Patent, com filtro por
jurisdição).

Isolamento, conforme o plano:
- `LENS_TOKEN` só no `.env`. Ausente → `RuntimeError` explícito, nunca falha silenciosa.
- Toda resposta carrega `licenca: "[FONTE: Lens.org - token de avaliacao, uso interno]"`.
  Constante única no topo do arquivo; sai com uma linha quando a assinatura entrar. Há
  teste que faz dessa remoção uma decisão consciente, não um acidente.
- Servidor independente no `.mcp.json` — remover o Lens não toca em `uspto` nem `epo`.
- Regra correspondente já está em `references/protocolo-citacao.md`: documento cuja única
  origem é o Lens não entra em entregável de cliente durante a avaliação.

## Aceite ao vivo

| # | Critério | Resultado |
| :-- | :--- | :--- |
| 1 | Servidor sobe e lista as 2 tools | ✅ |
| 2 | Busca de patente com filtro de jurisdição retorna dado real | ✅ ver abaixo |
| 3 | Busca de NPL retorna ≥5 artigos com DOI, título, ano, autores | ❌ **bloqueado pelo 401** |
| 4 | Falha de autorização é diagnosticada, não crua | ✅ a mensagem explica que os produtos são assinaturas separadas |

Critério 2 (dado real):

```
BR-102023000639-A2  ·  publicado 2023-06-27
LIQUID BASE PRODUCT, ... BIODEGRADABLE PRODUCT FABRICATION PROCESS
titular:         ISOCARE SOLUCOES AMBIENTAIS S/A
família simples: 18 membros
```

## Verificação — 8 testes offline

`.venv\Scripts\python.exe -m pytest lens -q` → **8 passed**. Total do projeto: **29**.

Cobrem: preferência por título em inglês na lista multilíngue, `dict` único vs lista,
desempacotamento de `{"value": ...}`, token ausente, **401 diagnosticado como produtos
separados** (regressão do achado acima) e 429 como limite de requisições.

## Pendências

- [ ] Solicitar acesso à **Scholarly API**. Sem isso o A3 não tem como ser decidido.
- [ ] Com o acesso: rodar os 5 casos reais já pesquisados em A1+A2 e tabelar, por caso,
      quantas NPL só o Lens trouxe e **quantas seriam materialmente destrutivas de
      novidade sob o art. 11**. Esse segundo número decide a assinatura.
- [ ] Preencher antes do dia 14 do trial.
