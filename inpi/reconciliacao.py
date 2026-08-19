"""Reconciliacao cross-fonte de um pedido BR (Fase 1.2, ponto 4).

PROBLEMA QUE RESOLVE: as fontes deste projeto nao conversam entre si. O estado
processual sai da base INPI local (despachos); o status da familia no exterior
sai do EPO/INPADOC; as reivindicacoes vem do enriquecimento (Google Patents); o
ledger real de anuidades pagas vem do pePI raspado (ficha_anuidades). Cada uma
sabe algo que as outras nao sabem -- e as vezes UMA CONTRADIZ A OUTRA. Um pedido
"em exame" no INPI cujo equivalente US ja foi concedido ha anos e um sinal forte
que nenhuma fonte isolada revela.

O QUE FAZ: cruza essas fontes por IMPORT DIRETO (este projeto nunca fala MCP-a-MCP;
cruza chamando as funcoes Python), MARCA divergencias e PROMOVE explicitamente o
dado que uma fonte secundaria tem e o INPI nao -- para que uma resposta sobre um
pedido BR carregue a informacao mais completa disponivel, sempre com procedencia.

DEEP MODULE: a interface publica e uma funcao -- reconciliar(numero). Toda a
complexidade (motor de estados, cascata de referencia do EPO, ledger vs projecao,
tolerancia a tabela ausente) fica escondida nos helpers privados.

REGRA DE OURO do projeto, mantida aqui: nada disto e veredito. O exterior (INPADOC)
e registro do PASSADO e atrasa; a base local vai ate a ultima RPI carregada. Cada
bloco declara 'fonte' e 'confianca' justamente para o humano pesar a divergencia,
nao para automatizar decisao sobre ela.
"""

from __future__ import annotations

from inpi import anuidades as anu
from inpi.consulta import _ficha_extras, _linhas, normaliza_numero
from inpi.prazos import _carregar_lote


def reconciliar(numero_inpi: str, incluir_exterior: bool = True) -> dict:
    """Cruza as fontes de um pedido BR e devolve o quadro reconciliado.

    USE QUANDO: for responder sobre UM pedido BR e quiser o dado mais completo e
    as contradicoes entre fontes explicitas -- nao so o que o INPI diz.

    Args:
        numero_inpi: em qualquer forma usual ('BR 10 2022 010731 2',
            'BR-102022010731-A2', '102022010731', 'PI0803071').
        incluir_exterior: True consulta o EPO (familia INPADOC + status legal),
            que gasta quota e e mais lento. False pula o exterior -- para respostas
            rapidas e para teste sem rede.

    Returns:
        dict com 'estado_inpi', 'familia_exterior', 'divergencias' (lista),
        'campos_promovidos' (lista) e 'fontes_consultadas'. Cada bloco de dado
        carrega 'fonte' e 'confianca'.
    """
    num = normaliza_numero(numero_inpi)

    # Estado processual local. _carregar_lote roda o mesmo motor de estados que
    # inpi_anuidades/inpi_prazos_carteira (uma so verdade sobre "vivo/morto",
    # anuidades em aberto, despacho terminal) -- nao reimplementamos nada disso.
    estados, _ = _carregar_lote(numeros=[num])
    est = estados.get(num)
    if not est or not est["despachos"]:
        return {
            "numero_inpi": num,
            "erro": True,
            "mensagem": (
                "Sem despachos na base INPI local para este numero. Sem estado "
                "processual nao ha o que reconciliar -- confira o numero em "
                "inpi_processo."
            ),
        }

    sigilo = _sigilo(num)
    extras = _ficha_extras(num)  # {} quando a coleta do pePI nao cobriu o pedido

    estado_inpi = _estado_inpi(est, sigilo)
    familia_exterior = _familia_exterior(num, incluir_exterior)
    claims = _claims_enriquecidos(num)

    divergencias = _divergencias(estado_inpi, familia_exterior, extras, est, sigilo)
    promovidos = _campos_promovidos(estado_inpi, familia_exterior, extras, claims)

    fontes = ["base INPI local (despachos)"]
    if extras:
        fontes.append("pePI raspado (ficha_extras)")
    if claims:
        fontes.append(claims["fonte"])
    if familia_exterior.get("consultado"):
        fontes.append("EPO OPS / INPADOC")

    return {
        "numero_inpi": num,
        "estado_inpi": estado_inpi,
        "familia_exterior": familia_exterior,
        "divergencias": divergencias,
        "campos_promovidos": promovidos,
        "fontes_consultadas": fontes,
        "aviso": (
            "Reconciliacao, nao veredito. Divergencia e sinal para o operador conferir, "
            "nao decisao automatica. O exterior (INPADOC) atrasa e a base local vai so "
            "ate a ultima RPI carregada; pese cada bloco pela sua 'fonte' e 'confianca'."
        ),
    }


# ---------------------------------------------------------------------------
# Estado processual local (base INPI)
# ---------------------------------------------------------------------------


def _sigilo(num: str) -> bool:
    """True se o pedido esta em sigilo na biblio (art. 30 LPI). Coluna 'sigilo'
    e nula na maioria; so marcamos sigilo quando ha valor nao-vazio."""
    r = _linhas("SELECT sigilo FROM biblio WHERE numero_inpi = ? LIMIT 1", [num])
    return bool(r and r[0].get("sigilo"))


def _estado_inpi(est: dict, sigilo: bool) -> dict:
    """Situacao processual derivada dos despachos VIVOS (nao anulados).

    9.1 e a carta-patente (concedido); 9.2 o indeferimento; 'encerrado_em' vem do
    despacho terminal ja tratado pelo motor de estados (com reversao por recurso).
    'vivo' = nao ha terminal em vigor.
    """
    vivos = [d for d in est["despachos"] if not d.get("anulado_em")]
    codigos = {str(d.get("codigo_despacho")) for d in vivos}
    encerrado = est["encerrado_em"]
    concedido = "9.1" in codigos

    if concedido and not encerrado:
        situacao = "concedido_vigente"
    elif concedido and encerrado:
        situacao = "concedido_extinto"
    elif "9.2" in codigos and encerrado:
        situacao = "indeferido"
    elif encerrado:
        situacao = "arquivado_ou_extinto"
    else:
        situacao = "em_exame_ou_pendente"

    term = est.get("despacho_terminal")
    return {
        "situacao": situacao,
        "vivo": encerrado is None,
        "concedido": concedido,
        "sigilo": sigilo,
        "encerrado_em": str(encerrado) if encerrado else None,
        "despacho_terminal": (
            {"codigo": term["codigo_despacho"], "data_rpi": str(term["data_rpi"])}
            if term else None
        ),
        "anuidades_em_aberto": est["anuidades_em_aberto"],
        "fonte": "base INPI local (despachos)",
        # Alta: o historico de despachos do INPI e a fonte primaria e completa do
        # andamento BR nesta base. So nao sabe o que foi protocolado e ainda nao
        # publicado, nem o que e posterior a ultima RPI carregada.
        "confianca": "alta",
    }


# ---------------------------------------------------------------------------
# Familia no exterior (EPO / INPADOC) -- consulta de rede, gated por incluir_exterior
# ---------------------------------------------------------------------------


def _familia_exterior(num: str, incluir: bool) -> dict:
    """Membros estrangeiros da familia INPADOC + status legal por pais.

    Duas chamadas EPO (familia e status legal), ambas cacheadas em disco pelo
    proprio modulo de origem. So roda com incluir=True.
    """
    if not incluir:
        return {
            "consultado": False,
            "nota": "incluir_exterior=False -- exterior nao consultado (poupa quota EPO).",
        }

    from inpi.familia_epo import familia

    fam = familia(num)
    if fam.get("erro"):
        return {
            "consultado": True,
            "erro": fam["erro"],
            "membros": [],
            "fonte": "EPO OPS / INPADOC",
            "confianca": "media",
        }

    # So os membros FORA do BR interessam: o BR ja e a fonte primaria acima.
    estr = [m for m in fam.get("membros", []) if m.get("pais") and m["pais"] != "BR"]
    paises_concedidos = {m["pais"] for m in estr if m.get("concedida")}

    caducados, taxa_paga, leg_erro = _status_legal_paises(num)

    # Pais "vivo" = concedido ou com taxa nacional paga, e sem caducidade reportada.
    # ponytail: heuristica -- INPADOC atrasa, ausencia de caducidade nao prova vida.
    # Por isso 'confianca: media' e o aviso viaja junto. Refinar so se um caso real
    # mostrar que taxa_paga/caducou se contradizem no mesmo pais.
    paises_vivos = sorted((paises_concedidos | set(taxa_paga)) - set(caducados))

    return {
        "consultado": True,
        "total_membros_estrangeiros": len(estr),
        "paises": sorted({m["pais"] for m in estr}),
        "membros": [
            {
                "pais": m["pais"],
                "referencia": m.get("referencia"),
                "concedida": m.get("concedida"),
                "data_publicacao": m.get("data_publicacao"),
            }
            for m in estr
        ],
        "algum_concedido": bool(paises_concedidos),
        "algum_vivo": bool(paises_vivos),
        "paises_vivos": paises_vivos,
        "caducado_em": sorted(caducados),
        "taxa_nacional_paga_em": sorted(taxa_paga),
        **({"aviso_status_legal": leg_erro} if leg_erro else {}),
        "fonte": "EPO OPS / INPADOC",
        # Media: familia e status legal INPADOC atrasam e dependem do escritorio
        # nacional reportar ao EPO. Bom para "existe equivalente concedido", fraco
        # para "esta vivo hoje".
        "confianca": "media",
    }


def _status_legal_paises(num: str) -> tuple[list[str], list[str], str | None]:
    """(caducados, taxa_paga, erro) do status legal INPADOC. Best-effort: qualquer
    falha de rede vira erro textual, nunca derruba a reconciliacao."""
    try:
        from epo.epo_mcp import epo_status_legal

        leg = epo_status_legal(f"BR{num}")
    except Exception as exc:  # rede/credencial/quota -- exterior e opcional
        return [], [], f"{type(exc).__name__}: {exc}"
    if not leg.get("encontrado"):
        return [], [], leg.get("mensagem")
    return leg.get("caducado_em", []), leg.get("taxa_nacional_paga_em", []), None


# ---------------------------------------------------------------------------
# Reivindicacoes enriquecidas (enriquecimento: Google Patents) -- best-effort
# ---------------------------------------------------------------------------


def _claims_enriquecidos(num: str) -> dict | None:
    """Reivindicacoes coletadas pelo pacote enriquecimento, se houver para este
    numero. A base de dados abertos do INPI NAO traz texto de reivindicacao --
    quando existe aqui, e dado que so a fonte secundaria tem."""
    try:
        from enriquecimento.db import con as ecu

        r = _rows(
            ecu(),
            "SELECT fonte, status, doc_id FROM claims "
            "WHERE numero_normalizado = ? AND status = 'ok' LIMIT 1",
            [num],
        )
    except Exception:
        return None  # banco de enriquecimento ausente/indisponivel -- opcional
    if not r:
        return None
    return {
        "disponivel": True,
        "doc_id": r[0].get("doc_id"),
        "fonte": f"enriquecimento ({r[0].get('fonte')})",
        "confianca": "media",
    }


def _rows(conn, sql: str, params: list) -> list[dict]:
    """_linhas para uma conexao arbitraria (o enriquecimento tem con() proprio)."""
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Deteccao de divergencias e promocao de campos
# ---------------------------------------------------------------------------


def _divergencias(estado: dict, fam: dict, extras: dict, est: dict,
                  sigilo: bool) -> list[dict]:
    """Contradicoes entre fontes -- cada uma com detalhe, fontes e acao sugerida."""
    out: list[dict] = []
    exterior = fam.get("consultado")

    # 1) INPI ainda em exame, mas o exterior ja concedeu ou ja deixou caducar.
    #    Sinal forte: o equivalente andou (ou ate expirou) enquanto o BR espera.
    if exterior and estado["situacao"] == "em_exame_ou_pendente":
        if fam.get("algum_concedido") or fam.get("caducado_em"):
            out.append({
                "tipo": "exterior_adiantado",
                "detalhe": (
                    f"INPI '{estado['situacao']}', mas na familia ha "
                    f"{'concessao' if fam.get('algum_concedido') else 'caducidade'} "
                    f"no exterior (concedido em {fam.get('paises_vivos') or '-'}, "
                    f"caducado em {fam.get('caducado_em') or '-'})."
                ),
                "fontes": ["base INPI local (despachos)", "EPO OPS / INPADOC"],
                "acao_sugerida": (
                    "Puxe o equivalente concedido (claims e citacoes ja definidos la) "
                    "para instruir o exame BR; se ja caducou fora, reavalie o interesse."
                ),
            })

    # 2) INPI concedido e vivo, mas a familia inteira ja morreu no exterior.
    if (exterior and estado["situacao"] == "concedido_vigente"
            and fam.get("total_membros_estrangeiros")
            and not fam.get("algum_vivo") and fam.get("caducado_em")):
        out.append({
            "tipo": "familia_morta_exterior",
            "detalhe": (
                "INPI concedido/vigente, mas nenhum membro estrangeiro consta vivo "
                f"e ha caducidade em {fam['caducado_em']}. O titular pode ja nao ter "
                "interesse comercial na tecnologia fora do BR."
            ),
            "fontes": ["base INPI local (despachos)", "EPO OPS / INPADOC"],
            "acao_sugerida": (
                "Confirme com o cliente se mantem a anuidade BR -- a familia abandonada "
                "fora sugere reavaliar o custo de manutencao aqui."
            ),
        })

    # 3) Anuidade cobrada como em aberto pelo INPI, mas o ledger real mostra paga.
    #    Contradicao direta entre despacho (projecao/notificacao) e realizado (pePI).
    em_aberto = set(est["anuidades_em_aberto"])
    for a in extras.get("anuidades_pagas", []):
        n = a.get("numero")
        pago = a.get("data_pagamento") or str(a.get("status") or "").lower() in {
            "paga", "pago", "quitada", "quitado"
        }
        if n in em_aberto and pago:
            out.append({
                "tipo": "anuidade_paga_mas_cobrada",
                "detalhe": (
                    f"{n}a anuidade consta EM ABERTO num despacho do INPI, mas o ledger "
                    f"raspado do pePI a mostra paga (GRU {a.get('gru')}, "
                    f"{a.get('data_pagamento')}). Provavel pagamento/restauracao "
                    "posterior ao despacho de cobranca."
                ),
                "fontes": ["base INPI local (despachos)", "pePI raspado (ficha_anuidades)"],
                "acao_sugerida": (
                    "Prefira o ledger realizado: a anuidade parece quitada. Confirme na GRU."
                ),
            })

    # 4) Pedido em sigilo no INPI, mas a familia ja foi publicada fora.
    if exterior and sigilo and fam.get("total_membros_estrangeiros"):
        out.append({
            "tipo": "sigilo_vazado_exterior",
            "detalhe": (
                "Pedido em sigilo no INPI (art. 30 LPI), mas ha membros publicados na "
                f"familia INPADOC ({fam.get('paises')}). O conteudo ja e publico fora."
            ),
            "fontes": ["base INPI local (biblio.sigilo)", "EPO OPS / INPADOC"],
            "acao_sugerida": (
                "O teor ja esta acessivel no exterior -- o sigilo BR nao protege mais o "
                "conteudo. Util para busca de anterioridade e para decisao de negocio."
            ),
        })

    return out


def _campos_promovidos(estado: dict, fam: dict, extras: dict,
                       claims: dict | None) -> list[dict]:
    """Campos que uma fonte secundaria forneceu e o INPI (dados abertos) nao tinha."""
    out: list[dict] = []

    # A base de dados abertos so tem IPC; o CPC vem do pePI raspado.
    if extras.get("cpc"):
        out.append({
            "campo": "cpc",
            "valor": extras["cpc"],
            "fonte": "pePI raspado (ficha_extras)",
            "confianca": "alta",
        })
    # Ledger REALIZADO de anuidades -- o INPI so publica consequencia, nao pagamento.
    if extras.get("anuidades_pagas"):
        out.append({
            "campo": "anuidades_pagas",
            "resumo": f"{len(extras['anuidades_pagas'])} anuidade(s) com ledger real",
            "fonte": "pePI raspado (ficha_anuidades)",
            "confianca": "alta",
        })
    # Texto de reivindicacao -- inexistente na base de dados abertos do INPI.
    if claims:
        out.append({
            "campo": "reivindicacoes",
            "valor": claims.get("doc_id"),
            "fonte": claims["fonte"],
            "confianca": claims["confianca"],
        })
    # Data de concessao no exterior quando o BR ainda nao concedeu: preenche a lacuna.
    if (fam.get("consultado") and fam.get("algum_concedido")
            and not estado["concedido"]):
        concedidos = [m for m in fam.get("membros", []) if m.get("concedida")]
        out.append({
            "campo": "concessao_no_exterior",
            "valor": [
                {"pais": m["pais"], "referencia": m["referencia"],
                 "data_publicacao": m["data_publicacao"]}
                for m in concedidos
            ],
            "fonte": "EPO OPS / INPADOC",
            "confianca": "media",
        })

    return out
