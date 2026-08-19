"""Gaps de protecao internacional: onde o titular AINDA pode entrar em fase
nacional (PCT) e provavelmente deveria -- mas ainda nao entrou.

A pergunta de negocio (Fase 3.1, ponto 5): "este cliente tem pedidos PCT perto
do prazo-limite de entrada em fase nacional e NAO protegeu em paises que importam
para ele?". O valor esta em transformar um prazo processual (art. 22/39 do PCT)
numa decisao ESTRATEGICA de cobertura -- e a decisao de PAIS nao pode ser lista
fixa, tem de sair de sinais reais do proprio titular e do mercado.

Disciplina conservadora do repo (a mesma de jurisdicoes.py e prazos.py):
  - O prazo de fase nacional NAO e recalculado aqui. Sai inteiro de
    inpi_prazo_fase_nacional (30/31 meses da prioridade mais antiga, PCT art. 22
    e 39). Perder esse prazo e irreversivel na maioria dos paises -- por isso
    projetamos, mas mandamos confirmar com o associado.
  - A recomendacao de PAIS e ORIENTATIVA, nunca veredito. Combina tres sinais
    (footprint do titular, tamanho de mercado da tecnologia, onde a concorrencia
    protege) num score comparativo -- e um ponto de partida para a conversa
    estrategica, nao uma ordem de deposito.

Fontes por sinal (cada uma declara a propria confianca):
  - marco/prazo  -> jurisdicoes.fase_nacional via inpi_prazo_fase_nacional (PCT)
  - ja protegido -> familia INPADOC (familia_epo), cache-first, degrada p/ vazio
  - mercado/concorrencia -> landscape (BigQuery/Google Patents), cache-first
  - footprint    -> paises das familias do proprio titular (INPADOC)
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from inpi.consulta import _linhas, normaliza_numero
from inpi.prazos import inpi_prazo_fase_nacional
from inpi.titulares import chave_de, resolver

# Pesos do score de pais. Mercado/concorrencia pesa mais que footprint: footprint
# diz "ja teve interesse", mercado diz "onde a tecnologia se protege hoje". Nao ha
# calibracao empirica destes pesos (nao ha ground-truth de "decisao acertada"),
# entao sao heuristica declarada -- por isso o resultado e orientativo.
_PESO_MERCADO = 0.6
_PESO_FOOTPRINT = 0.4


def _numeros_titular(titular: str) -> tuple[str | None, list[str]]:
    """(chave canonica, numeros do portfolio BR). Preferimos a chave canonica
    (mesma de inpi_perfil_titular); se a tabela `titulares` nao existir neste
    banco ou nada casar, caimos para ILIKE do nome cru.

    ponytail: fallback ILIKE junta grafias distintas (o motivo pelo qual a chave
    canonica existe). E rede de seguranca para banco parcial/piloto -- em producao
    a chave canonica responde primeiro.
    """
    chave = None
    try:
        chave = chave_de(titular)
        if chave:
            rows = _linhas(
                """SELECT DISTINCT dp.numero_inpi FROM depositantes dp
                   JOIN titulares t ON t.original = dp.depositante
                   WHERE t.chave = ?""",
                [chave],
            )
            if rows:
                return chave, [r["numero_inpi"] for r in rows]
    except Exception:
        pass  # banco sem tabela titulares -> fallback abaixo
    rows = _linhas(
        "SELECT DISTINCT numero_inpi FROM depositantes WHERE depositante ILIKE ?",
        [f"%{titular.strip()}%"],
    )
    return chave, [r["numero_inpi"] for r in rows]


def _pedidos_pct(numeros: list[str]) -> list[dict]:
    """Pedidos de ORIGEM PCT do lote (numero_pct preenchido), com deposito e a
    prioridade mais antiga -- a data-base do prazo de fase nacional."""
    if not numeros:
        return []
    rows = _linhas(
        """WITH alvo AS (SELECT unnest(?::VARCHAR[]) AS numero_inpi)
           SELECT b.numero_inpi,
                  min(b.data_deposito)   AS data_deposito,
                  any_value(b.numero_pct) AS numero_pct,
                  min(pr.data_prioridade) AS prioridade
           FROM biblio b JOIN alvo USING (numero_inpi)
           LEFT JOIN prioridades pr USING (numero_inpi)
           WHERE b.numero_pct IS NOT NULL
           GROUP BY b.numero_inpi""",
        [numeros],
    )
    return rows


def _ipc_por_numero(numeros: list[str]) -> dict[str, list[str]]:
    if not numeros:
        return {}
    rows = _linhas(
        """WITH alvo AS (SELECT unnest(?::VARCHAR[]) AS numero_inpi)
           SELECT i.numero_inpi, i.simbolo FROM ipc i JOIN alvo USING (numero_inpi)""",
        [numeros],
    )
    saida: dict[str, list[str]] = {}
    for r in rows:
        if r["simbolo"]:
            saida.setdefault(r["numero_inpi"], []).append(r["simbolo"])
    return saida


def _cpc_prefixos(simbolos: list[str]) -> list[str]:
    """IPC -> prefixo de classificacao (4 chars, nivel de subclasse). IPC e CPC
    coincidem ate a subclasse (ex. 'A61K'); o landscape aceita prefixo. Ver
    carteira_bridge.py, mesma aproximacao."""
    return sorted({s[:4] for s in simbolos if s and len(s) >= 4})


def _marco_fase_nacional(prioridade: date, hoje: date) -> dict | None:
    """Marco e dias restantes do prazo de fase nacional, REUTILIZANDO o motor
    do PCT (nao recalcula aqui). Devolve o prazo MAIS PROXIMO (tipicamente 30
    meses); jurisdicoes de 31 meses tem alguns dias a mais -- ver aviso."""
    r = inpi_prazo_fase_nacional(prioridade.isoformat())
    prazos = r.get("prazos") or []
    if not prazos:
        return None
    marco = prazos[0]["prazo"]  # ja vem ordenado do mais proximo ao mais distante
    dias = (date.fromisoformat(marco) - hoje).days
    return {"marco": marco, "dias": dias, "prazo_mais_distante": prazos[-1]["prazo"]}


def _paises_familia(numero: str) -> list[str]:
    """Paises onde ESTE pedido ja tem membro de familia INPADOC. Cache-first;
    sem rede/credencial degrada para lista vazia (nunca derruba a analise)."""
    from inpi.familia_epo import familia

    try:
        d = familia(numero)
    except Exception:
        return []
    return sorted({m["pais"] for m in d.get("membros", []) if m.get("pais")})


def _landscape_paises(prefixos: list[str], cache: dict, incluir: bool) -> dict[str, int]:
    """Depositos por pais nas tecnologias (prefixos CPC) do pedido -- proxy de
    tamanho de mercado E de onde a concorrencia protege (sao os mesmos documentos).
    Cache-first no proprio landscape; aqui memoizamos por prefixo dentro da chamada
    para nao repetir consulta entre pedidos da mesma tecnologia."""
    if not incluir:
        return {}
    from landscape import consultas
    from landscape.mcp_app import _rodar

    total: Counter[str] = Counter()
    for pref in prefixos:
        if pref not in cache:
            try:
                r = _rodar("evolucao_temporal", consultas.evolucao_temporal,
                           {"cpc_prefix": pref, "pais": None, "desde": None, "ate": None})
                cache[pref] = r.get("linhas", [])
            except Exception as exc:
                cache[pref] = {"erro": f"{type(exc).__name__}: {exc}"}
        linhas = cache[pref]
        if isinstance(linhas, dict):  # erro memoizado
            continue
        for ln in linhas:
            pais = ln.get("pais")
            if pais and pais != "BR":
                total[pais] += int(ln.get("depositos") or 0)
    return dict(total)


def _rankear_paises(mercado: dict[str, int], footprint: Counter,
                    ja_protegido: set[str], top: int) -> list[dict]:
    """Combina mercado (landscape) e footprint (familias do titular) num score
    0-1 por pais, exclui onde ja ha protecao e o BR, e justifica cada sugestao."""
    candidatos = (set(mercado) | set(footprint)) - ja_protegido - {"BR"}
    if not candidatos:
        return []
    max_m = max(mercado.values(), default=0) or 1
    max_f = max(footprint.values(), default=0) or 1

    saida = []
    for pais in candidatos:
        m, f = mercado.get(pais, 0), footprint.get(pais, 0)
        score = round(_PESO_MERCADO * (m / max_m) + _PESO_FOOTPRINT * (f / max_f), 3)
        partes = []
        if m:
            partes.append(f"mercado/concorrencia: {m} depositos na tecnologia (landscape)")
        if f:
            partes.append(f"footprint do titular: protege em {f} outra(s) familia(s)")
        saida.append({
            "pais": pais,
            "score": score,
            "justificativa": " + ".join(partes) or "sinal fraco (sem mercado nem footprint)",
        })
    saida.sort(key=lambda x: (-x["score"], x["pais"]))
    return saida[:top]


def inpi_gaps_protecao(titular: str, dias_janela: int = 180, hoje: str | None = None,
                       top_paises: int = 5, incluir_landscape: bool = True,
                       incluir_familia: bool = True) -> dict:
    """Pedidos PCT do titular perto do prazo de fase nacional (art. 22/39) e os
    paises importantes onde ele AINDA nao protegeu.

    Para cada pedido de origem PCT cujo prazo de fase nacional vence dentro de
    `dias_janela` (e ainda nao venceu), lista onde ja ha protecao (familia
    INPADOC) e recomenda paises faltantes por score combinado de mercado
    (landscape/BigQuery) e footprint do proprio titular.

    Args:
        titular: nome do cliente/titular (resolvido pela chave canonica).
        dias_janela: so pedidos cujo marco vence em ate N dias (padrao 180).
        hoje: 'AAAA-MM-DD' de referencia; sem isso usa a data corrente.
        top_paises: quantos paises sugerir por pedido (1 a 20).
        incluir_landscape: False para nao bater no BigQuery (ranking so por
            footprint) -- use offline/sem credencial.
        incluir_familia: False para nao consultar a familia INPADOC (sem rede);
            'ja_protegido_em' e o footprint ficam vazios.
    """
    ref = date.fromisoformat(hoje) if hoje else date.today()
    top_paises = max(1, min(top_paises, 20))
    chave, numeros = _numeros_titular(titular)
    avisos = [
        "Prazo de fase nacional contado da PRIORIDADE MAIS ANTIGA (PCT art. 22 e 39); "
        "'marco' e o prazo mais proximo (30 meses) -- jurisdicoes de 31 meses tem alguns "
        "dias a mais. Perder este prazo e irreversivel na maioria dos paises: confirme com "
        "o associado.",
        "Recomendacao de pais e ORIENTATIVA (score comparativo), nao conselho definitivo.",
    ]

    pedidos = _pedidos_pct(numeros)
    ipc = _ipc_por_numero([p["numero_inpi"] for p in pedidos])

    # 1a passada: quem esta na janela (nao precisa de rede -- so o motor de prazo).
    em_janela = []
    sem_prioridade = 0
    for p in pedidos:
        prio = p["prioridade"]
        if not prio:
            sem_prioridade += 1
            continue
        marco = _marco_fase_nacional(prio, ref)
        if not marco:
            continue
        if 0 <= marco["dias"] <= dias_janela:
            p["_marco"] = marco
            em_janela.append(p)

    # 2a passada (cara): familia + landscape so para os pedidos que entraram.
    footprint: Counter[str] = Counter()  # paises onde o titular protege (sinal global)
    protegido_por_pedido: dict[str, list[str]] = {}
    for p in em_janela:
        paises = _paises_familia(p["numero_inpi"]) if incluir_familia else []
        protegido_por_pedido[p["numero_inpi"]] = paises
        footprint.update(paises)

    ls_cache: dict = {}
    saida_pedidos = []
    recomendados_global: Counter[str] = Counter()
    for p in em_janela:
        num = p["numero_inpi"]
        prefixos = _cpc_prefixos(ipc.get(num, []))
        mercado = _landscape_paises(prefixos, ls_cache, incluir_landscape)
        ja = set(protegido_por_pedido.get(num, []))
        faltando = _rankear_paises(mercado, footprint, ja, top_paises)
        for f in faltando:
            recomendados_global[f["pais"]] += 1
        saida_pedidos.append({
            "numero_inpi": num,
            "numero_pct": p["numero_pct"],
            "data_deposito": str(p["data_deposito"]) if p["data_deposito"] else None,
            "prioridade_mais_antiga": str(p["prioridade"]),
            "marco_fase_nacional": p["_marco"]["marco"],
            "dias_restantes": p["_marco"]["dias"],
            "prazo_mais_distante_31m": p["_marco"]["prazo_mais_distante"],
            "ja_protegido_em": sorted(ja),
            "classificacoes": prefixos,
            "paises_importantes_faltando": faltando,
        })
    saida_pedidos.sort(key=lambda x: x["dias_restantes"])

    if not incluir_landscape:
        avisos.append("Sem landscape: ranking de pais sai so do footprint do titular.")
    if not incluir_familia:
        avisos.append("Sem familia INPADOC: 'ja_protegido_em' e footprint ficam vazios.")
    if sem_prioridade:
        avisos.append(f"{sem_prioridade} pedido(s) PCT sem prioridade na base -- sem "
                      "data-base nao ha prazo projetavel; ficaram de fora.")

    return {
        "titular": titular,
        "normalizacao": resolver(chave),
        "parametros": {"dias_janela": dias_janela, "referencia": ref.isoformat(),
                       "top_paises": top_paises, "incluir_landscape": incluir_landscape,
                       "incluir_familia": incluir_familia},
        "pedidos_em_janela": saida_pedidos,
        "resumo": {
            "pedidos_pct_no_portfolio": len(pedidos),
            "pedidos_em_risco": len(saida_pedidos),
            "paises_mais_recomendados": [
                {"pais": pais, "pedidos": n}
                for pais, n in recomendados_global.most_common(top_paises)
            ],
        },
        "avisos": avisos,
    }
