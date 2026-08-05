"""Quadro global de anuidades de um cliente: Brasil (INPI) + exterior (familia EPO).

O Brasil sai do INPI, que e completo e calibrado. O exterior sai da familia INPADOC,
e a data e ESTIMATIVA -- as regras estrangeiras nao foram revisadas por profissional
habilitado, e para varias jurisdicoes a anuidade conta da CONCESSAO, data que a
familia INPADOC nao traz.

Por isso cada linha carrega a coluna 'confianca':
  calculado   Brasil, regra do art. 84 calibrada contra 285.409 despachos
  estimado    exterior, regra da tabela, contada do deposito
  indisponivel  exterior cuja regra conta da concessao -- sem a data, nao ha estimativa
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

import anuidades as anu  # noqa: E402
import jurisdicoes as jur  # noqa: E402


def _regra_de(pais: str, kind: str | None):
    """Resolve a regra aplicavel. Kind 'T*' e traducao de patente europeia validada.

    DK, ES, PT, FI e TR aparecem como jurisdicoes proprias, mas quando o kind e T*
    o documento e uma validacao nacional de um EP -- e a regra e a de EP-nac, nao a
    nacional generica. A linha EP-nac ja existia no CSV e nunca era consultada,
    porque o lookup usava so o codigo do pais.
    """
    regras = jur.carregar()
    if kind and kind.upper().startswith("T"):
        r = regras.get("EP-NAC")
        if r:
            return r, True
    return regras.get(pais.upper()), False


def _vencimentos(r, base: date) -> list[tuple[int, date]]:
    """(numero da anuidade, data de vencimento) segundo a periodicidade da regra."""
    if r.periodicidade == "marcos":
        # Anos fracionarios contados da data-base: US paga em 3,5 / 7,5 / 11,5 anos
        # da concessao. O 'numero da anuidade' aqui e o marco arredondado, que e
        # como o USPTO nomeia ('4TH YEAR', '8TH YEAR').
        return [
            (int(m) + 1, anu._mais_meses(base, int(round(m * 12))))
            for m in r.marcos
        ]
    return [
        (n, anu._mais_anos(base, n - 1))
        for n in range(r.primeira or 1, r.vigencia_anos + 1)
    ]


def _anuidades_estrangeiras(pais: str, data_deposito: date | None, hoje: date,
                            ate: date, data_concessao: date | None = None,
                            criterio: str = "vencimento",
                            kind: str | None = None) -> list[dict]:
    """Janelas de anuidade de um pais, pela regra da tabela. Estimativa.

    criterio='vencimento' (padrao): entra quem VENCE dentro do periodo. E a leitura
        literal de "anuidades a pagar ate tal data".
    criterio='janela': entra tambem quem apenas ABRE o prazo no periodo, mesmo
        vencendo depois.
    """
    r, via_ep = _regra_de(pais, kind)
    if not r:
        return [{"confianca": "sem_regra",
                 "nota": f"Jurisdicao {pais} nao esta em anuidades-por-jurisdicao.csv"}]

    base = data_concessao if r.data_base == "concessao" else data_deposito

    # Pedido AINDA NAO CONCEDIDO em jurisdicao que conta da concessao NAO TEM
    # anuidade devida -- em JP e KR o 1o ao 3o ano sao pagos NA concessao. Isso e
    # resposta, nao lacuna: antes saia como 'indisponivel', que dizia "nao sei"
    # sobre algo que se sabe.
    if r.data_base == "concessao" and not data_concessao:
        return [{"confianca": "sem_anuidade_nesta_fase",
                 "nota": (f"{r.nome}: {r.tipo_taxa} conta da concessao, e este caso "
                          "ainda e pedido em exame. Nao ha anuidade devida nesta fase; "
                          "passa a haver quando conceder.")}]
    if not base:
        return [{"confianca": "indisponivel",
                 "nota": (f"{r.nome}: sem data de {r.data_base} para este caso. "
                          "Confirme com o associado local.")}]

    saida = []
    # Alguns paises cobram o primeiro bloco logo apos a concessao, fora do
    # calendario anual: MX em 2 meses, CL em 60 dias uteis.
    if r.dias_apos_concessao and data_concessao:
        venc = anu._mais_meses(data_concessao, 0)
        venc = date.fromordinal(venc.toordinal() + r.dias_apos_concessao)
        fim = anu._mais_meses(venc, r.graca_meses) if r.graca_meses else venc
        if (hoje <= venc <= ate) if criterio == "vencimento" else (
                venc <= ate and fim >= hoje):
            saida.append({
                "anuidade": 0,
                "inicio": venc.isoformat(),
                "vencimento": venc.isoformat(),
                "fim_com_graca": fim.isoformat(),
                "confianca": jur.rotulo(r),
                "data_base_usada": f"concessao {data_concessao.isoformat()}",
                "nota": (f"1o pagamento pos-concessao ({r.dias_apos_concessao} dias). "
                         f"{r.base_legal}"
                         + ("" if r.projeta else " — REGRA NAO REVISADA")),
            })

    for n, ini in _vencimentos(r, base):
        fim = anu._mais_meses(ini, r.graca_meses) if r.graca_meses else ini
        # O VENCIMENTO e a data ordinaria; a graca e prorrogacao com sobretaxa.
        # Filtrar pelo fim da graca jogava para fora anuidades que vencem dentro do
        # periodo -- a 12a de um EP validado vence 09/11/2026, mas com 6 meses de
        # graca o fim caia em 2027 e a linha sumia.
        # Vencida mas ainda dentro da graca continua DEVIDA, e e a mais urgente:
        # so da para pagar com sobretaxa e o relogio esta correndo. Filtrar so por
        # 'vence daqui pra frente' escondia justamente essas -- a 4a da ZA venceu
        # em 21/04/2026 e some, embora a graca va ate outubro.
        dentro = (hoje <= ini <= ate or (ini < hoje <= fim))             if criterio == "vencimento" else (ini <= ate and fim >= hoje)
        if dentro:
            saida.append({
                "anuidade": n,
                "inicio": ini.isoformat(),
                "vencimento": ini.isoformat(),
                "fim_com_graca": fim.isoformat(),
                "confianca": jur.rotulo(r),
                "data_base_usada": f"{r.data_base} {base.isoformat()}"
                                   + (" (via EP-nac)" if via_ep else ""),
                "nota": (f"{r.base_legal}"
                         + ("" if r.projeta
                            else " — REGRA NAO REVISADA, confirme com o associado")),
            })
    # Sem vencimento na janela nao vira linha: quem pergunta "o que vence ate X"
    # nao quer ver os casos que nao vencem.
    return saida


def _concessao_por_pedido(membros: list[dict]) -> dict:
    """Mapa (pais, numero_pedido) -> data de concessao.

    O membro com kind B*/C* e a patente concedida, e a data daquela publicacao e a
    data de concessao. Casa com o pedido pelo numero do PEDIDO, nao pelo da
    publicacao: nos EUA o pedido publicado (A1) e a patente (B2) tem numeros
    diferentes.
    """
    mapa: dict = {}
    for mb in membros:
        if not mb.get("concedida") or not mb.get("data_publicacao"):
            continue
        d = mb["data_publicacao"]
        try:
            dt = date(int(d[:4]), int(d[4:6]), int(d[6:8]))
        except Exception:
            continue
        chave = (mb["pais"], mb.get("numero_pedido"))
        if chave[1] and (chave not in mapa or dt < mapa[chave]):
            mapa[chave] = dt
        # tambem indexa por pais, para o caso de o numero de pedido faltar
        mapa.setdefault((mb["pais"], None), dt)
    return mapa


def montar(titular: str, ate: str, hoje: str | None = None,
           criterio: str = "vencimento") -> dict:
    """Quadro Brasil + exterior de um cliente."""
    import inpi_mcp as m
    from familia_epo import familia

    d_hoje = date.fromisoformat(hoje) if hoje else date.today()
    d_ate = date.fromisoformat(ate)

    estados, _ = m._carregar_lote(titular=titular)
    linhas: list[dict] = []

    # --- Brasil: fonte INPI ---
    br = m.inpi_prazos_carteira(titular=titular, tipos=["anuidade"],
                                de=d_hoje.isoformat(), ate=d_ate.isoformat(),
                                limite_resultados=5000)
    nums = sorted({p["numero_inpi"] for p in br["prazos"]})
    cur = m.con().execute(
        """SELECT dp.numero_inpi, arg_max(dp.depositante, 1) AS cliente
           FROM depositantes dp WHERE dp.numero_inpi IN (SELECT unnest(?::VARCHAR[]))
           GROUP BY 1""", [nums or [""]])
    nome_cli = {r[0]: r[1] for r in cur.fetchall()}

    for p in br["prazos"]:
        # inpi_prazos_carteira filtra por intersecao de janela. Com criterio
        # 'vencimento', mantem so o que de fato vence no periodo -- senao o mesmo
        # caso aparece com duas anuidades seguidas, uma vencendo fora da janela.
        if criterio == "vencimento" and not (
            d_hoje.isoformat() <= p["prazo"] <= d_ate.isoformat()
        ):
            continue
        linhas.append({
            "cliente": nome_cli.get(p["numero_inpi"], ""),
            "numero_oficial": f"BR {p['numero_inpi']}",
            "pais": "BR",
            "anuidade": p["descricao"],
            "inicio": p.get("inicio"),
            "vencimento": p["prazo"],
            "situacao": p["status"],
            "confianca": "calculado",
            "fonte": "INPI — LPI art. 84",
        })

    # --- Exterior: familia INPADOC ---
    vistos: set = set()
    cob = {"casos_ativos": 0, "com_familia": 0, "sem_familia_consultada": []}
    for num_br, est in estados.items():
        if est["encerrado_em"]:
            continue
        cob["casos_ativos"] += 1
        fam = familia(num_br)
        # Uma familia que nao veio nao pode ser silencio: sem contador, um cliente
        # com 60% dos casos em erro de consulta le o quadro como se fosse completo.
        if fam.get("erro"):
            cob["sem_familia_consultada"].append(num_br)
        elif fam.get("membros"):
            cob["com_familia"] += 1
        concessoes = _concessao_por_pedido(fam.get("membros", []))
        cli = nome_cli.get(num_br) or ""
        if not cli:
            r = m.con().execute(
                "SELECT arg_max(depositante,1) FROM depositantes WHERE numero_inpi=?",
                [num_br]).fetchone()
            cli = r[0] if r else ""
        # Um PEDIDO pode ter varias publicacoes: 'EP-4502115-A1' e '-A4', ou
        # 'KR-20160103019-A' (pedido) e 'KR-102235205-B1' (patente concedida, com
        # numero diferente). Anuidade e por pedido, entao agrupa por numero do
        # PEDIDO e escolhe uma publicacao para representar -- de preferencia a
        # concedida, que e o numero que o associado usa.
        por_pedido: dict = {}
        for mb in fam.get("membros", []):
            if mb["pais"] in ("BR", "WO") or not mb.get("data_deposito"):
                continue
            chave = (mb["pais"], mb.get("numero_pedido") or mb["numero"])
            atual = por_pedido.get(chave)
            if atual is None or (mb.get("concedida") and not atual.get("concedida")):
                por_pedido[chave] = mb

        for chave_pedido, mb in por_pedido.items():
            if chave_pedido in vistos:
                continue
            vistos.add(chave_pedido)
            d = mb["data_deposito"]
            try:
                dep = date(int(d[:4]), int(d[4:6]), int(d[6:8])) if len(d) == 8 \
                    else date.fromisoformat(d[:10])
            except Exception:
                continue
            conc = (concessoes.get((mb["pais"], mb.get("numero_pedido")))
                    or concessoes.get((mb["pais"], None)))
            for a in _anuidades_estrangeiras(mb["pais"], dep, d_hoje, d_ate,
                                             data_concessao=conc, criterio=criterio,
                                             kind=mb.get("kind")):
                if a["confianca"] in ("indisponivel", "sem_regra",
                                      "sem_anuidade_nesta_fase"):
                    # A 'situacao' vem do motivo REAL, nao mais fixa no codigo. Antes
                    # dizia "regra conta da concessao" para todos, o que era falso em
                    # 14 das 24 linhas -- a causa la era periodicidade nao suportada.
                    linhas.append({
                        "cliente": cli, "numero_oficial": mb["referencia"],
                        "pais": mb["pais"], "anuidade": "—",
                        "inicio": None, "vencimento": None,
                        "situacao": {
                            "sem_anuidade_nesta_fase": "pedido em exame — nada devido",
                            "sem_regra": "jurisdição fora da tabela",
                            "indisponivel": "falta data-base",
                        }[a["confianca"]],
                        "confianca": a["confianca"], "fonte": a["nota"],
                        "equivalente_br": num_br,
                    })
                    break
                linhas.append({
                    "cliente": cli, "numero_oficial": mb["referencia"],
                    "pais": mb["pais"], "anuidade": f"{a['anuidade']}a anuidade",
                    "inicio": a["inicio"], "vencimento": a["vencimento"],
                    "fim_com_graca": a["fim_com_graca"],
                    # O rotulo vem da regra, nao do caminho: assinar uma jurisdicao
                    # (revisado_por + revisado_em no CSV) vira 'calculado' aqui sem
                    # tocar em codigo. Ver jurisdicoes.rotulo.
                    "situacao": ("calculado pela regra do país"
                                 if a["confianca"] == "calculado"
                                 else "estimado pela regra do país"),
                    "confianca": a["confianca"], "fonte": a["nota"],
                    "equivalente_br": num_br,
                })

    linhas.sort(key=lambda x: (x["vencimento"] or "9999", x["pais"],
                               x["numero_oficial"]))
    return {
        "titular": titular,
        "ate": d_ate.isoformat(),
        "total": len(linhas),
        "por_confianca": {
            k: n for k, n in sorted(
                {c: sum(1 for l in linhas if l["confianca"] == c)
                 for c in {l["confianca"] for l in linhas}}.items(),
                key=lambda x: -x[1])
        },
        "com_data": sum(1 for l in linhas if l["vencimento"]),
        "cobertura": {
            "casos_ativos": cob["casos_ativos"],
            "com_familia_no_exterior": cob["com_familia"],
            "sem_familia_consultada": len(cob["sem_familia_consultada"]),
            "numeros_sem_familia": cob["sem_familia_consultada"],
            "alerta": (
                f"{len(cob['sem_familia_consultada'])} de {cob['casos_ativos']} casos "
                "ativos NAO tiveram a familia consultada com sucesso no EPO. Podem ter "
                "equivalentes no exterior que nao aparecem neste quadro. Ausencia aqui "
                "nao e prova de ausencia de prazo."
            ) if cob["sem_familia_consultada"] else "",
        },
        "por_pais": {
            p: sum(1 for l in linhas if l["pais"] == p)
            for p in sorted({l["pais"] for l in linhas})
        },
        "linhas": linhas,
    }


def exportar(titular: str, ate: str, hoje: str | None = None,
             saida: str | None = None, criterio: str = "vencimento") -> dict:
    """Gera o XLSX do quadro global."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    q = montar(titular, ate, hoje, criterio=criterio)
    wb = Workbook()
    ws = wb.active
    ws.title = "Anuidades BR + exterior"

    ws["A1"] = (f"{titular.upper()} — anuidades até {q['ate']} — "
                f"gerado em {date.today():%d/%m/%Y}")
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = (
        "BRASIL (confiança 'calculado'): regra do art. 84 da LPI, calibrada contra "
        "285.409 despachos reais. EXTERIOR ('estimado'): regra transcrita da legislação, "
        "NÃO revisada por profissional habilitado — confirme a data com o associado local "
        "antes de agir. 'indisponível': a anuidade conta da CONCESSÃO e a família INPADOC "
        "não traz essa data. 'sem_anuidade_nesta_fase': pedido ainda em exame numa jurisdição "
        "que só cobra após a concessão — não há nada devido agora. Em nenhum caso isto é "
        "fatura: a base não sabe o que já foi pago."
    )
    if q["cobertura"]["alerta"]:
        ws["A2"] = ws["A2"].value + " ⚠️ COBERTURA: " + q["cobertura"]["alerta"] +             " Casos: " + ", ".join(q["cobertura"]["numeros_sem_familia"])
    ws["A2"].font = Font(size=9, italic=True, color="9C0006")
    ws.merge_cells("A2:J2")
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[2].height = 68

    cols = [("cliente", "Cliente (grafia)", 40), ("numero_oficial", "Número oficial", 22),
            ("pais", "País", 7), ("anuidade", "Anuidade", 14),
            ("vencimento", "Vencimento", 14), ("fim_com_graca", "Limite c/ sobretaxa", 18),
            ("confianca", "Confiança", 22), ("situacao", "Situação", 26),
            ("equivalente_br", "Equiv. BR", 15),
            ("fonte", "Regra / observação", 62)]
    for i, (_, rot, larg) in enumerate(cols, 1):
        c = ws.cell(row=4, column=i, value=rot)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="D9D9D9")
        ws.column_dimensions[get_column_letter(i)].width = larg

    fills = {"calculado": PatternFill("solid", fgColor="C6EFCE"),
             "estimado": PatternFill("solid", fgColor="FFEB9C"),
             "sem_anuidade_nesta_fase": PatternFill("solid", fgColor="DDEBF7"),
             "indisponivel": PatternFill("solid", fgColor="F2F2F2"),
             "sem_regra": PatternFill("solid", fgColor="FFC7CE")}
    for ln, item in enumerate(q["linhas"], start=5):
        for i, (campo, _, _) in enumerate(cols, 1):
            ws.cell(row=ln, column=i, value=item.get(campo))
        f = fills.get(item["confianca"])
        if f:
            ws.cell(row=ln, column=7).fill = f
    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:J{max(4, len(q['linhas']) + 4)}"

    destino = Path(saida) if saida else (
        RAIZ.parent / "docs" / "relatorios" /
        f"anuidades_global_{titular.lower().replace(' ', '_')}_{q['ate']}.xlsx")
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    q["arquivo"] = str(destino)
    q.pop("linhas", None)
    return q
