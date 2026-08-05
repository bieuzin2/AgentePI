"""Relatorios de prazos em XLSX, para o docketing conferir.

Este modulo NAO calcula nada. Ele serializa o que inpi_prazos_carteira ja produz,
acrescentando o que o operador precisa para trabalhar: cliente, titulo, faixa de
urgencia e uma coluna vazia para marcar a conferencia.

O aviso do topo de cada aba nao e formalidade. A base registra consequencia, nao
vencimento futuro; pagamento em dia nao gera despacho. Quem recebe a planilha
precisa ver isso antes de agir.

Uso:
    from inpi.relatorios import gerar_prazos
    gerar_prazos(escritorio="Clarke Modet", de="2026-08-01", ate="2026-10-31")
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

RAIZ = Path(__file__).resolve().parent

AVISO = (
    "PROJEÇÃO CALCULADA, NÃO CONSULTADA. O INPI publica consequência, não vencimento "
    "futuro. Pagamento em dia não gera despacho, portanto esta base não sabe o que já "
    "foi pago. Use como lista de conferência contra o controle de prazos do escritório "
    "— não substitui o docketing nem o procurador responsável."
)

CM_AZUL = colors.HexColor("#0b2f4f")
CM_CIANO = colors.HexColor("#00a3e0")
CM_CINZA = colors.HexColor("#6b7280")
CM_CLARO = colors.HexColor("#eff6fb")
CM_FUNDO = colors.HexColor("#f8fafc")
CM_VERMELHO = colors.HexColor("#b91c1c")
CM_VERDE = colors.HexColor("#047857")
CM_AMARELO = colors.HexColor("#92400e")

PDF_TITULO = ParagraphStyle(
    "CM_TITULO",
    parent=getSampleStyleSheet()["Title"],
    fontName="Helvetica-Bold",
    fontSize=18,
    leading=22,
    textColor=CM_AZUL,
    spaceAfter=6,
)
PDF_SUBTITULO = ParagraphStyle(
    "CM_SUBTITULO",
    parent=getSampleStyleSheet()["BodyText"],
    fontName="Helvetica",
    fontSize=9,
    leading=12,
    textColor=CM_CINZA,
    spaceAfter=10,
)
PDF_SECAO = ParagraphStyle(
    "CM_SECAO",
    parent=getSampleStyleSheet()["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=12,
    leading=14,
    textColor=CM_AZUL,
    spaceBefore=10,
    spaceAfter=6,
)
PDF_BODY = ParagraphStyle(
    "CM_BODY",
    parent=getSampleStyleSheet()["BodyText"],
    fontName="Helvetica",
    fontSize=9,
    leading=12,
    textColor=colors.black,
)
PDF_BODY_SMALL = ParagraphStyle(
    "CM_BODY_SMALL",
    parent=PDF_BODY,
    fontSize=8,
    leading=10,
)
PDF_CAB = ParagraphStyle(
    "CM_CAB",
    parent=PDF_BODY,
    fontName="Helvetica-Bold",
    fontSize=8,
    leading=9,
    textColor=colors.white,
)



def _p(texto: str, estilo: ParagraphStyle = PDF_BODY) -> Paragraph:
    return Paragraph((texto or "").replace("\n", "<br/>"), estilo)



def _resumo_kpis(prazos: list[dict]) -> dict[str, int]:
    return {
        "total": len(prazos),
        "vermelho": sum(1 for p in prazos if p.get("urgencia") == "VERMELHO"),
        "amarelo": sum(1 for p in prazos if p.get("urgencia") == "amarelo"),
        "verde": sum(1 for p in prazos if p.get("urgencia") == "verde"),
        "sem_data": sum(1 for p in prazos if p.get("prazo") is None),
        "clientes": len({p.get("cliente") or "(sem titular)" for p in prazos}),
    }



def _linha_periodo(p: dict) -> list[str]:
    return [
        str(p.get("numero_inpi") or ""),
        str(p.get("cliente") or ""),
        str(p.get("titulo") or ""),
        str(p.get("descricao") or ""),
        str(p.get("prazo") or ""),
        str(p.get("urgencia") or ""),
    ]



def _estilo_pdf(destino: Path) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(destino),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
    )



def _header_footer(canvas, doc, criterio: str) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(CM_AZUL)
    canvas.rect(0, height - 18 * mm, width, 18 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(16 * mm, height - 11 * mm, "ClarkeModet")
    canvas.setFont("Helvetica", 7.5)
    canvas.drawRightString(width - 16 * mm, height - 11 * mm, criterio[:110])
    canvas.setStrokeColor(CM_CIANO)
    canvas.setLineWidth(0.8)
    canvas.line(16 * mm, height - 19 * mm, width - 16 * mm, height - 19 * mm)
    canvas.setFillColor(CM_CINZA)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(16 * mm, 10 * mm, "Relatório gerado pelo agente de patentes")
    canvas.drawRightString(width - 16 * mm, 10 * mm, f"Página {doc.page}")
    canvas.restoreState()



def gerar_prazos_pdf(
    escritorio: str | None = None,
    titular: str | None = None,
    numeros: list[str] | None = None,
    de: str | None = None,
    ate: str | None = None,
    saida: str | None = None,
) -> dict:
    """Gera PDF com resumo executivo e tabela de prazos."""
    from inpi import inpi_mcp as mcp_mod

    d_ini = date.fromisoformat(de) if de else date.today()
    d_fim = date.fromisoformat(ate) if ate else mcp_mod.anu._mais_meses(d_ini, 3)

    r = mcp_mod.inpi_prazos_carteira(
        titular=titular,
        procurador=escritorio,
        numeros=numeros,
        de=d_ini.isoformat(),
        ate=d_fim.isoformat(),
        limite_resultados=20000,
    )
    if r.get("erro"):
        return r

    prazos = r["prazos"]
    _enriquece(prazos, mcp_mod.con())
    for p in prazos:
        pz = p.get("prazo")
        p["dias"] = (date.fromisoformat(pz) - d_ini).days if pz else None
        p["urgencia"] = _urgencia(p["dias"], p["tipo"])

    quem = escritorio or titular or f"{len(numeros or [])} processos"
    criterio = (f"Prazos de {quem} — {d_ini.strftime('%d/%m/%Y')} a "
                f"{d_fim.strftime('%d/%m/%Y')} — gerado em "
                f"{date.today().strftime('%d/%m/%Y')}")

    destino = Path(saida) if saida else (
        RAIZ.parent / "docs" / "relatorios" /
        f"prazos_{(escritorio or titular or 'carteira').lower().replace(' ', '_')}"
        f"_{d_ini:%Y%m}_{d_fim:%Y%m}.pdf"
    )
    destino.parent.mkdir(parents=True, exist_ok=True)

    resumo = _resumo_kpis(prazos)
    story = [
        _p("ClarkeModet", PDF_TITULO),
        _p(criterio, PDF_SUBTITULO),
        _p("Resumo executivo", PDF_SECAO),
        Table(
            [
                [
                    _p("Total de prazos", PDF_CAB),
                    _p("Vermelho", PDF_CAB),
                    _p("Amarelo", PDF_CAB),
                    _p("Verde", PDF_CAB),
                    _p("Sem data", PDF_CAB),
                    _p("Clientes", PDF_CAB),
                ],
                [
                    resumo["total"], resumo["vermelho"], resumo["amarelo"],
                    resumo["verde"], resumo["sem_data"], resumo["clientes"],
                ],
            ],
            colWidths=[28 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm],
        ),
        Spacer(1, 6),
        _p(AVISO, PDF_BODY_SMALL),
        _p("Top 20 prazos", PDF_SECAO),
    ]

    top = [
        ["Processo", "Cliente", "Título", "Prazo", "Urgência", "Base legal"],
        *[
            [
                p.get("numero_inpi") or "",
                p.get("cliente") or "",
                p.get("titulo") or "",
                p.get("prazo") or "",
                p.get("urgencia") or "",
                p.get("base_legal") or "",
            ]
            for p in prazos[:20]
        ],
    ]
    tabela = Table(top, repeatRows=1, colWidths=[22 * mm, 34 * mm, 48 * mm, 22 * mm, 18 * mm, 40 * mm])
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CM_AZUL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("LEADING", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.35, CM_CINZA),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CM_FUNDO, CM_CLARO]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tabela)

    if len(prazos) > 20:
        story += [Spacer(1, 6), _p(f"{len(prazos) - 20} prazos adicionais omitidos do PDF.", PDF_BODY_SMALL)]

    pdf = _estilo_pdf(destino)
    pdf.build(story, onFirstPage=lambda c, d: _header_footer(c, d, criterio), onLaterPages=lambda c, d: _header_footer(c, d, criterio))

    return {
        "arquivo": str(destino),
        "criterio": r["criterio"],
        "total_prazos": len(prazos),
        "por_tipo": r["resumo"]["por_tipo"],
        "por_urgencia": {
            u: sum(1 for p in prazos if p["urgencia"] == u)
            for u in ("VERMELHO", "amarelo", "verde")
        },
        "clientes": resumo["clientes"],
        "truncado": r.get("truncado", False),
    }



# Faixas de urgencia. Art. 33 e recurso sao fatais e nao tem prazo complementar,
# por isso entram em vermelho ja a 90 dias.
_VERMELHO = PatternFill("solid", fgColor="FFC7CE")
_AMARELO = PatternFill("solid", fgColor="FFEB9C")
_VERDE = PatternFill("solid", fgColor="C6EFCE")
_CABECALHO = PatternFill("solid", fgColor="D9D9D9")

COLUNAS = [
    ("numero_inpi", "Processo", 16),
    ("cliente", "Cliente", 38),
    ("titulo", "Título", 46),
    ("descricao", "Prazo", 32),
    ("prazo", "Data limite", 13),
    ("dias", "Dias", 7),
    ("urgencia", "Urgência", 11),
    ("status", "Situação", 26),
    ("inicio", "Início ordinário", 15),
    ("fim_ordinario", "Fim ordinário", 14),
    ("base_legal", "Base legal", 30),
    ("alerta", "Alerta", 44),
    ("conferido", "[ ] conferido", 14),
]


def _urgencia(dias: int | None, tipo: str) -> str:
    if dias is None:
        return "sem data"
    fatal = tipo in ("exame", "recurso")
    if dias <= (90 if fatal else 30):
        return "VERMELHO"
    if dias <= (180 if fatal else 60):
        return "amarelo"
    return "verde"


def _enriquece(prazos: list[dict], con) -> None:
    """Acrescenta cliente e titulo. Uma query para todos, nao uma por processo."""
    nums = sorted({p["numero_inpi"] for p in prazos})
    if not nums:
        return
    cur = con.execute(
        """SELECT dp.numero_inpi,
                  arg_max(dp.depositante, 1) AS cliente,
                  any_value(c.titulo) AS titulo
           FROM depositantes dp
           LEFT JOIN conteudo c USING (numero_inpi)
           WHERE dp.numero_inpi IN (SELECT unnest(?::VARCHAR[]))
           GROUP BY dp.numero_inpi""",
        [nums],
    )
    por_num = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    for p in prazos:
        cli, tit = por_num.get(p["numero_inpi"], (None, None))
        p["cliente"] = cli
        p["titulo"] = tit


def _aba(wb: Workbook, nome: str, prazos: list[dict], criterio: str) -> None:
    ws = wb.create_sheet(nome[:31])
    ws["A1"] = criterio
    ws["A1"].font = Font(bold=True, size=11)
    ws["A2"] = AVISO
    ws["A2"].font = Font(size=9, italic=True, color="9C0006")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(COLUNAS))
    ws.row_dimensions[2].height = 30
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")

    for i, (_, rotulo, larg) in enumerate(COLUNAS, start=1):
        cel = ws.cell(row=4, column=i, value=rotulo)
        cel.font = Font(bold=True)
        cel.fill = _CABECALHO
        ws.column_dimensions[get_column_letter(i)].width = larg

    for linha, p in enumerate(prazos, start=5):
        for i, (campo, _, _) in enumerate(COLUNAS, start=1):
            ws.cell(row=linha, column=i, value=p.get(campo))
        u = p.get("urgencia")
        if u == "VERMELHO":
            ws.cell(row=linha, column=7).fill = _VERMELHO
        elif u == "amarelo":
            ws.cell(row=linha, column=7).fill = _AMARELO
        elif u == "verde":
            ws.cell(row=linha, column=7).fill = _VERDE

    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:{get_column_letter(len(COLUNAS))}{max(4, len(prazos) + 4)}"


def gerar_prazos(
    escritorio: str | None = None,
    titular: str | None = None,
    numeros: list[str] | None = None,
    de: str | None = None,
    ate: str | None = None,
    saida: str | None = None,
) -> dict:
    """Gera o XLSX de prazos. Devolve o caminho e as contagens."""
    from inpi import inpi_mcp as mcp_mod

    d_ini = date.fromisoformat(de) if de else date.today()
    d_fim = date.fromisoformat(ate) if ate else mcp_mod.anu._mais_meses(d_ini, 3)

    r = mcp_mod.inpi_prazos_carteira(
        titular=titular,
        procurador=escritorio,
        numeros=numeros,
        de=d_ini.isoformat(),
        ate=d_fim.isoformat(),
        limite_resultados=20000,
    )
    if r.get("erro"):
        return r

    prazos = r["prazos"]
    _enriquece(prazos, mcp_mod.con())
    for p in prazos:
        pz = p.get("prazo")
        p["dias"] = (date.fromisoformat(pz) - d_ini).days if pz else None
        p["urgencia"] = _urgencia(p["dias"], p["tipo"])
        p["conferido"] = ""

    quem = escritorio or titular or f"{len(numeros or [])} processos"
    criterio = (f"Prazos de {quem} — {d_ini.strftime('%d/%m/%Y')} a "
                f"{d_fim.strftime('%d/%m/%Y')} — gerado em "
                f"{date.today().strftime('%d/%m/%Y')}")

    wb = Workbook()
    wb.remove(wb.active)

    # Resumo primeiro: e o que o socio olha.
    resumo = wb.create_sheet("Resumo")
    resumo["A1"] = criterio
    resumo["A1"].font = Font(bold=True, size=12)
    resumo["A3"] = "Por tipo de prazo"
    resumo["A3"].font = Font(bold=True)
    linha = 4
    for cab in ("Tipo", "Total", "Vermelho", "Amarelo", "Verde"):
        resumo.cell(row=linha, column=("Tipo", "Total", "Vermelho", "Amarelo",
                                       "Verde").index(cab) + 1, value=cab).font = Font(bold=True)
    for tipo in sorted({p["tipo"] for p in prazos}):
        linha += 1
        do_tipo = [p for p in prazos if p["tipo"] == tipo]
        resumo.cell(row=linha, column=1, value=tipo)
        resumo.cell(row=linha, column=2, value=len(do_tipo))
        for col, u in ((3, "VERMELHO"), (4, "amarelo"), (5, "verde")):
            resumo.cell(row=linha, column=col,
                        value=sum(1 for p in do_tipo if p["urgencia"] == u))

    linha += 3
    resumo.cell(row=linha, column=1, value="Por cliente (top 30)").font = Font(bold=True)
    linha += 1
    for cab, col in (("Cliente", 1), ("Prazos", 2), ("Vermelho", 3)):
        resumo.cell(row=linha, column=col, value=cab).font = Font(bold=True)
    por_cliente: dict[str, list] = {}
    for p in prazos:
        por_cliente.setdefault(p.get("cliente") or "(sem titular)", []).append(p)
    for cli, ps in sorted(por_cliente.items(), key=lambda x: -len(x[1]))[:30]:
        linha += 1
        resumo.cell(row=linha, column=1, value=cli)
        resumo.cell(row=linha, column=2, value=len(ps))
        resumo.cell(row=linha, column=3,
                    value=sum(1 for p in ps if p["urgencia"] == "VERMELHO"))
    resumo.column_dimensions["A"].width = 46
    for c in "BCDE":
        resumo.column_dimensions[c].width = 11

    resumo.cell(row=linha + 2, column=1, value=AVISO).font = Font(size=9, italic=True,
                                                                 color="9C0006")
    resumo.merge_cells(start_row=linha + 2, start_column=1, end_row=linha + 2,
                       end_column=5)
    resumo.cell(row=linha + 2, column=1).alignment = Alignment(wrap_text=True,
                                                              vertical="top")
    resumo.row_dimensions[linha + 2].height = 46

    rotulos = {"anuidade": "Anuidades", "exame": "Exame art 33",
               "recurso": "Recursos", "vigencia": "Vigencia",
               "exigencia": "Exigencias"}
    for tipo in sorted({p["tipo"] for p in prazos}):
        do_tipo = sorted([p for p in prazos if p["tipo"] == tipo],
                         key=lambda x: (x.get("prazo") or "9999"))
        _aba(wb, rotulos.get(tipo, tipo), do_tipo, criterio)

    destino = Path(saida) if saida else (
        RAIZ.parent / "docs" / "relatorios" /
        f"prazos_{(escritorio or titular or 'carteira').lower().replace(' ', '_')}"
        f"_{d_ini:%Y%m}_{d_fim:%Y%m}.xlsx"
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)

    return {
        "arquivo": str(destino),
        "criterio": r["criterio"],
        "total_prazos": len(prazos),
        "por_tipo": r["resumo"]["por_tipo"],
        "por_urgencia": {
            u: sum(1 for p in prazos if p["urgencia"] == u)
            for u in ("VERMELHO", "amarelo", "verde")
        },
        "clientes": len(por_cliente),
        "truncado": r.get("truncado", False),
    }
