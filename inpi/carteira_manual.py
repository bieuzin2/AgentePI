"""Quadro de anuidades a partir da lista de docketing do cliente, nao da familia INPADOC.

Existe porque a descoberta por familia tem um teto que nenhum ajuste remove: uma
validacao de patente europeia em BE, FR, GB, GR, IE, IT, LU, NL ou SE nao gera
publicacao nacional (Acordo de Londres), logo nao existe membro INPADOC. Dos 59 casos
reais da Tecnored, 46 sao invisiveis a qualquer busca de familia. A lista do escritorio
e a unica fonte completa; o EPO entra so para datar cada familia.
"""

from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

import anuidades as anu
import jurisdicoes as jur

CARTEIRA = RAIZ / "referencias" / "carteira-tecnored.csv"
TAXAS = RAIZ / "referencias" / "taxas-anuidade.csv"


def _taxas() -> dict:
    """Valor oficial por (jurisdicao, ano). So entra aqui numero de fonte oficial.

    Deixar a celula vazia e melhor que preenche-la com estimativa de terceiro: taxa
    errada vira orcamento errado, e as fontes agregadas avisam elas mesmas que um
    numero de um ano atras nao serve para orcar pagamento.
    """
    t = {}
    for r in csv.DictReader(TAXAS.open(encoding="utf-8")):
        t[(r["jurisdicao"].upper(), int(r["ano"]))] = r
    return t

# Paises que contam o vencimento ate o ULTIMO DIA DO MES do aniversario, nao no dia.
# Trabalhar sempre pelo dia do aniversario e o conservador: o mes so adia, nunca
# antecipa. E a recomendacao do proprio guia de formalidades da CMS.
FIM_DE_MES = {"EP", "DE", "FR", "GB", "ZA"}


def _fim_do_mes(d: date) -> date:
    nxt = date(d.year + (d.month == 12), (d.month % 12) + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


def _regra(caso):
    regras = jur.carregar()
    # carregar() indexa em maiusculas -- 'EP-nac' nao acha, 'EP-NAC' acha. Com o
    # lookup errado toda validacao europeia caia no nome do pais e sumia.
    if caso["tipo"] == "EP-nac":
        return regras.get("EP-NAC")
    if caso["tipo"] == "EP-pendente":
        return regras.get("EP")
    return regras.get(caso["pais"].upper())


def proxima(caso: dict, hoje: date) -> dict:
    r = _regra(caso)
    base_txt = caso["data_base"]
    saida = {**caso, "anuidade": None, "vencimento": None, "limite_com_sobretaxa": None,
             "situacao": "", "regra": ""}
    if not base_txt:
        saida["situacao"] = "data-base desconhecida — confirmar com o associado"
        return saida
    if not r:
        saida["situacao"] = f"jurisdicao {caso['pais']} fora da tabela de regras"
        return saida

    base = date.fromisoformat(base_txt)
    conc = date.fromisoformat(caso["concessao"]) if caso.get("concessao") else None
    ancora = conc if r.data_base == "concessao" else base
    if r.data_base == "concessao" and not conc:
        saida["situacao"] = "anuidade conta da concessao, ainda nao concedida"
        saida["regra"] = r.base_legal
        return saida

    saida["regra"] = f"{r.nome}: anual a partir da {r.primeira}a, contada da {r.data_base}"
    for n in range(r.primeira or 1, r.vigencia_anos + 1):
        venc = anu._mais_anos(ancora, n - 1)
        if caso["pais"].upper() in FIM_DE_MES or caso["tipo"] == "EP-pendente":
            venc = _fim_do_mes(venc)
        fim = anu._mais_meses(venc, r.graca_meses)
        if venc >= hoje:
            saida.update(anuidade=n, vencimento=venc, limite_com_sobretaxa=fim,
                         situacao="a vencer")
            return saida
        if fim >= hoje:
            saida.update(anuidade=n, vencimento=venc, limite_com_sobretaxa=fim,
                         situacao="VENCIDA — ainda pagavel com sobretaxa")
            return saida
    saida["situacao"] = "fora da vigencia"
    return saida


def montar(hoje: date | None = None) -> list[dict]:
    hoje = hoje or date.today()
    casos = list(csv.DictReader(CARTEIRA.open(encoding="utf-8")))
    linhas = [proxima(c, hoje) for c in casos]
    tx = _taxas()
    for l in linhas:
        j = "EP" if l["tipo"] == "EP-pendente" else l["pais"].upper()
        n = l.get("anuidade")
        # EP fixa o valor do 10o ano em diante
        r = tx.get((j, n)) or (tx.get((j, 10)) if j == "EP" and n and n > 10 else None)
        l["taxa_oficial"] = f"{r['moeda']} {r['valor']}" if r else ""
        l["taxa_fonte"] = r["fonte"] if r else "taxa nao levantada — confirmar com o associado"
        l["sobretaxa"] = r["sobretaxa"] if r else ""
    linhas.sort(key=lambda x: (x["vencimento"] or date(9999, 1, 1), x["pais"]))
    return linhas


if __name__ == "__main__":
    hoje = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    ls = montar(hoje)
    print(f"{'PAIS':<5}{'NUMERO':<22}{'ANU':>4}  {'VENCIMENTO':<12}{'C/SOBRETAXA':<12} SITUACAO")
    for l in ls:
        v = l["vencimento"].strftime("%d/%m/%Y") if l["vencimento"] else "—"
        f = l["limite_com_sobretaxa"].strftime("%d/%m/%Y") if l["limite_com_sobretaxa"] else "—"
        a = f"{l['anuidade']}a" if l["anuidade"] else "—"
        print(f"{l['pais']:<5}{l['numero_oficial']:<22}{a:>4}  {v:<12}{f:<12}"
              f"{l.get('taxa_oficial',''):<12} {l['situacao']}")
    print(f"\ncom data: {sum(1 for l in ls if l['vencimento'])} de {len(ls)}")


def exportar(hoje: date | None = None, saida: str | None = None) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    ls = montar(hoje)
    wb = Workbook(); ws = wb.active; ws.title = "Anuidades Tecnored"
    ws["A1"] = f"TECNORED — anuidades da carteira estrangeira — posicao em {(hoje or date.today()):%d/%m/%Y}"
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = (
        "Fonte dos casos: lista de docketing do escritorio. A busca por familia INPADOC "
        "nao acha 46 destes 59 casos — validacao de EP em BE, FR, GB, GR, IE, IT, LU, NL e SE "
        "nao gera publicacao nacional (Acordo de Londres), logo nao existe membro de familia. "
        "DATAS: calculadas pela regra de cada jurisdicao a partir da data de deposito confirmada "
        "no EPO. As regras estrangeiras estao NAO-REVISADAS — confirme com o associado local. "
        "Onde o pais conta o vencimento ate o fim do mes (DE, FR, GB, ZA, EPO), a data do "
        "aniversario foi mantida por ser a conservadora. TAXAS: so preenchidas onde ha fonte "
        "oficial; celula vazia significa nao levantada, nunca isenta."
    )
    ws["A2"].font = Font(size=9, italic=True, color="9C0006")
    ws.merge_cells("A2:J2"); ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[2].height = 72

    cols = [("pais", "País", 7), ("numero_oficial", "Número oficial", 24),
            ("anuidade", "Anuidade", 10), ("vencimento", "Vencimento", 13),
            ("limite_com_sobretaxa", "Último dia c/ sobretaxa", 20),
            ("taxa_oficial", "Taxa oficial", 14), ("sobretaxa", "Sobretaxa", 11),
            ("situacao", "Situação", 34), ("familia", "Família", 14),
            ("taxa_fonte", "Fonte da taxa", 52)]
    for i, (_, rot, larg) in enumerate(cols, 1):
        c = ws.cell(row=4, column=i, value=rot)
        c.font = Font(bold=True); c.fill = PatternFill("solid", fgColor="D9D9D9")
        ws.column_dimensions[get_column_letter(i)].width = larg

    vermelho = PatternFill("solid", fgColor="FFC7CE")
    cinza = PatternFill("solid", fgColor="F2F2F2")
    for ln, it in enumerate(ls, start=5):
        for i, (campo, _, _) in enumerate(cols, 1):
            v = it.get(campo)
            cel = ws.cell(row=ln, column=i, value=v)
            if isinstance(v, date):
                cel.number_format = "DD/MM/YYYY"
        if it["situacao"].startswith("VENCIDA"):
            ws.cell(row=ln, column=8).fill = vermelho
        elif not it["vencimento"]:
            ws.cell(row=ln, column=8).fill = cinza
    ws.freeze_panes = "A5"; ws.auto_filter.ref = f"A4:J{len(ls) + 4}"
    destino = Path(saida) if saida else (
        RAIZ.parent / "docs" / "relatorios" / "anuidades_tecnored_carteira.xlsx")
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return str(destino)
