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


def _anuidades_estrangeiras(pais: str, data_deposito: date, hoje: date,
                            ate: date) -> list[dict]:
    """Janelas de anuidade de um pais, pela regra da tabela. Estimativa."""
    regras = jur.carregar()
    r = regras.get(pais.upper())
    if not r:
        return [{"confianca": "sem_regra",
                 "nota": f"Jurisdicao {pais} nao esta em anuidades-por-jurisdicao.csv"}]
    if r.data_base != "deposito":
        return [{"confianca": "indisponivel",
                 "nota": (f"{r.nome}: {r.tipo_taxa} contada da {r.data_base}. A familia "
                          "INPADOC nao traz a data de concessao, entao nao ha estimativa "
                          "possivel aqui. Confirme com o associado local.")}]
    if r.periodicidade != "anual" or not r.primeira:
        return [{"confianca": "indisponivel",
                 "nota": f"{r.nome}: periodicidade '{r.periodicidade}' nao suportada."}]

    saida = []
    for n in range(r.primeira, r.vigencia_anos + 1):
        ini = anu._mais_anos(data_deposito, n - 1)
        fim = anu._mais_meses(ini, r.graca_meses) if r.graca_meses else ini
        if ini <= ate and fim >= hoje:
            saida.append({
                "anuidade": n,
                "inicio": ini.isoformat(),
                "fim_com_graca": fim.isoformat(),
                "confianca": "estimado",
                "nota": f"{r.base_legal} — REGRA NAO REVISADA, confirme com o associado",
            })
    return saida


def montar(titular: str, ate: str, hoje: str | None = None) -> dict:
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
    for num_br, est in estados.items():
        if est["encerrado_em"]:
            continue
        fam = familia(num_br)
        cli = nome_cli.get(num_br) or ""
        if not cli:
            r = m.con().execute(
                "SELECT arg_max(depositante,1) FROM depositantes WHERE numero_inpi=?",
                [num_br]).fetchone()
            cli = r[0] if r else ""
        for mb in fam.get("membros", []):
            if mb["pais"] in ("BR", "WO") or not mb.get("data_deposito"):
                continue
            # Dedup por (pais, numero) SEM o kind code: 'EP-4502115-A1' e
            # 'EP-4502115-A4' sao publicacoes do mesmo pedido, e anuidade e por
            # pedido. Manter as duas inflava a conta.
            chave_pedido = (mb["pais"], mb["numero"])
            if chave_pedido in vistos:
                continue
            vistos.add(chave_pedido)
            try:
                dep = date.fromisoformat(mb["data_deposito"][:10])
            except Exception:
                continue
            for a in _anuidades_estrangeiras(mb["pais"], dep, d_hoje, d_ate):
                if a["confianca"] in ("indisponivel", "sem_regra"):
                    linhas.append({
                        "cliente": cli, "numero_oficial": mb["referencia"],
                        "pais": mb["pais"], "anuidade": "?",
                        "inicio": None, "vencimento": None,
                        "situacao": "regra conta da concessão",
                        "confianca": a["confianca"], "fonte": a["nota"],
                        "equivalente_br": num_br,
                    })
                    break
                linhas.append({
                    "cliente": cli, "numero_oficial": mb["referencia"],
                    "pais": mb["pais"], "anuidade": f"{a['anuidade']}a anuidade",
                    "inicio": a["inicio"], "vencimento": a["fim_com_graca"],
                    "situacao": "estimado pela regra do país",
                    "confianca": "estimado", "fonte": a["nota"],
                    "equivalente_br": num_br,
                })

    linhas.sort(key=lambda x: (x["vencimento"] or "9999", x["pais"],
                               x["numero_oficial"]))
    return {
        "titular": titular,
        "ate": d_ate.isoformat(),
        "total": len(linhas),
        "por_confianca": {
            k: sum(1 for l in linhas if l["confianca"] == k)
            for k in ("calculado", "estimado", "indisponivel", "sem_regra")
        },
        "por_pais": {
            p: sum(1 for l in linhas if l["pais"] == p)
            for p in sorted({l["pais"] for l in linhas})
        },
        "linhas": linhas,
    }


def exportar(titular: str, ate: str, hoje: str | None = None,
             saida: str | None = None) -> dict:
    """Gera o XLSX do quadro global."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    q = montar(titular, ate, hoje)
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
        "não traz essa data. Em nenhum caso isto é fatura: a base não sabe o que já foi pago."
    )
    ws["A2"].font = Font(size=9, italic=True, color="9C0006")
    ws.merge_cells("A2:H2")
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[2].height = 46

    cols = [("cliente", "Cliente (grafia)", 42), ("numero_oficial", "Número oficial", 22),
            ("pais", "País", 7), ("anuidade", "Anuidade", 14),
            ("inicio", "Início do prazo", 15), ("vencimento", "Vencimento", 14),
            ("confianca", "Confiança", 13), ("fonte", "Regra / observação", 62)]
    for i, (_, rot, larg) in enumerate(cols, 1):
        c = ws.cell(row=4, column=i, value=rot)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="D9D9D9")
        ws.column_dimensions[get_column_letter(i)].width = larg

    fills = {"calculado": PatternFill("solid", fgColor="C6EFCE"),
             "estimado": PatternFill("solid", fgColor="FFEB9C"),
             "indisponivel": PatternFill("solid", fgColor="F2F2F2"),
             "sem_regra": PatternFill("solid", fgColor="FFC7CE")}
    for ln, item in enumerate(q["linhas"], start=5):
        for i, (campo, _, _) in enumerate(cols, 1):
            ws.cell(row=ln, column=i, value=item.get(campo))
        f = fills.get(item["confianca"])
        if f:
            ws.cell(row=ln, column=7).fill = f
    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:H{max(4, len(q['linhas']) + 4)}"

    destino = Path(saida) if saida else (
        RAIZ.parent / "docs" / "relatorios" /
        f"anuidades_global_{titular.lower().replace(' ', '_')}_{q['ate']}.xlsx")
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    q["arquivo"] = str(destino)
    q.pop("linhas", None)
    return q
