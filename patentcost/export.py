"""Exporta o portfólio público PROVÁVEL de um titular para o contrato de entrada do PatentCost.

Titularidade em base pública não prova pagamento nem quem gere o caso: cada caso leva `fonte` e
`confianca` ('confirmado' = dado oficial do INPI; 'inferido' = membro de família INPADOC).
"""
from __future__ import annotations

import re
from pathlib import Path

from openpyxl import load_workbook

from inpi.familia_epo import familia

# Desfechos que encerram o caso (dados abertos do INPI). 21.6 = notificação de anuidade não paga/extinção,
# sujeita a anulação posterior (21.8) — tratada por _anulados().
FIM = {"11.1": "abandonada", "11.2": "abandonada", "9.2": "abandonada", "21.6": "extinta", "24.1": "extinta", "24.2": "extinta"}
_RE_ANULA = re.compile(r"[Aa]nulad[ao] a publica\S* c[oó]digo\s*(\d+\.\d+)\s*na RPI\s*(\d+)")


def modalidade_de(numero: str) -> str:
    n = (numero or "").upper().replace(" ", "")
    return "MU" if n.startswith("MU") or n.startswith("20") or n.startswith("BR20") else "PI"


def secao_ipc(ipc: str | None) -> str | None:
    s = (ipc or "").strip()
    return s[0].upper() if s[:1].isalpha() else None


def data_iso(v: str | None) -> str | None:
    s = str(v or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s) else None


def _anulados(despachos: list[dict]) -> set[tuple[str, int]]:
    out = set()
    for d in despachos:
        m = _RE_ANULA.search(d.get("complemento_despacho") or "")
        if m:
            out.add((m.group(1), int(m.group(2))))
    return out


def classificar_status(despachos: list[dict]) -> tuple[str, str | None]:
    anul = _anulados(despachos)
    ds = sorted((d for d in despachos if (str(d["codigo_despacho"]), int(d.get("numero_rpi") or 0)) not in anul and str(d["codigo_despacho"]) != "21.8"),
                key=lambda d: str(d["data_rpi"]))
    concessao = next((data_iso(str(d["data_rpi"])) for d in ds if str(d["codigo_despacho"]) == "16.1"), None)
    status = "concedida" if concessao else "pendente"
    for d in ds:
        if str(d["codigo_despacho"]) in FIM:
            status = FIM[str(d["codigo_despacho"])]
    return status, concessao


OBS = "Portfólio público provável; titularidade não prova pagamento nem gestão do caso."


def casos_br(chaves: list[str], cliente: str) -> list[dict]:
    """Casos BR de todas as chaves canônicas do titular (inpi_titular_resolver). Consulta a base do INPI."""
    from inpi.consulta import _linhas

    nums = [r["numero_inpi"] for r in _linhas(
        "SELECT DISTINCT dp.numero_inpi FROM depositantes dp JOIN titulares t ON t.original = dp.depositante WHERE list_contains(?, t.chave)", [chaves])]
    out = []
    for n in nums:
        b = (_linhas("""SELECT * FROM biblio WHERE numero_inpi = ? ORDER BY (data_protocolo IS NOT NULL)::INT + (data_publicacao IS NOT NULL)::INT
                        + (numero_pct IS NOT NULL)::INT DESC LIMIT 1""", [n]) or [{}])[0]
        desp = _linhas("SELECT codigo_despacho, CAST(data_rpi AS VARCHAR) data_rpi, numero_rpi, complemento_despacho FROM despachos WHERE numero_inpi = ?", [n])
        ipc = (_linhas("SELECT simbolo FROM ipc WHERE numero_inpi = ? ORDER BY ordem LIMIT 1", [n]) or [{}])[0].get("simbolo")
        tit = (_linhas("SELECT titulo FROM conteudo WHERE numero_inpi = ?", [n]) or [{}])[0].get("titulo")
        dep = (_linhas("SELECT string_agg(DISTINCT depositante, '; ') d FROM depositantes WHERE numero_inpi = ?", [n]) or [{}])[0].get("d")
        status, conc = classificar_status(desp)
        out.append({
            "id_caso": f"BR-{n}", "cliente": cliente, "jurisdicao": "BR", "modalidade": modalidade_de(n), "tipo_registro": "existente",
            "numero_pedido": n, "titulo": tit, "titular": dep, "rota": "pct_fase_nacional" if b.get("numero_pct") else "direta",
            "status": status, "data_deposito": data_iso(str(b.get("data_deposito") or "")), "data_concessao": conc,
            "ipc_cpc": ipc, "categoria_tecnologica": secao_ipc(ipc), "categoria_requerente": "grande", "familia": n,
            "fonte": "INPI dados abertos", "confianca": "confirmado" if b.get("data_deposito") else "inferido", "observacoes": OBS,
        })
    return out


def casos_familia(casos: list[dict]) -> list[dict]:
    """Membros estrangeiros da família INPADOC (EPO OPS, cacheado em disco) como casos inferidos."""
    out, vistos = [], set()
    for c in casos:
        fam = familia(c["numero_pedido"])
        for m in fam.get("membros", []):
            pais, num = m.get("pais"), m.get("numero")
            if not pais or not num or pais == "BR" or (pais, num) in vistos:
                continue
            vistos.add((pais, num))
            grant = data_iso(m.get("data_publicacao")) if m.get("concedida") else None
            out.append({
                "id_caso": f"{pais}-{num}", "cliente": c["cliente"], "jurisdicao": pais, "modalidade": c.get("modalidade", "PI"),
                "tipo_registro": "existente", "numero_pedido": m.get("numero_pedido") or num, "numero_patente": num if grant else None,
                "titulo": m.get("titulo") or c.get("titulo"), "status": "concedida" if grant else "pendente",
                "data_deposito": data_iso(m.get("data_deposito")), "data_concessao": grant, "ipc_cpc": c.get("ipc_cpc"),
                "categoria_tecnologica": c.get("categoria_tecnologica"), "categoria_requerente": "grande", "familia": c["familia"],
                "rota": "regional" if pais in ("EP", "EA", "AP", "OA") else "pct_fase_nacional" if c.get("rota") == "pct_fase_nacional" else "direta",
                "fonte": "EPO OPS INPADOC", "confianca": "inferido",
                "observacoes": OBS + " Status inferido pelo kind code da última publicação; validações EP e anuidades pagas não verificadas.",
            })
    return out


CAMPOS = ["id_caso", "cliente", "jurisdicao", "modalidade", "tipo_registro", "numero_pedido", "numero_patente", "familia", "titulo", "titular",
          "rota", "status", "data_deposito", "data_concessao", "ipc_cpc", "categoria_tecnologica", "categoria_requerente", "observacoes"]


def escrever_xlsx(casos: list[dict], modelo: Path, saida: Path) -> Path:
    """Preenche a aba Casos do modelo oficial do PatentCost (cabeçalho = chaves dos campos)."""
    wb = load_workbook(modelo)
    ws = wb["Casos"]
    cab = [c.value for c in ws[1]]
    col = {k: cab.index(k) + 1 for k in CAMPOS if k in cab}
    for i, c in enumerate(casos, 2):
        for k, j in col.items():
            v = c.get(k)
            if k == "observacoes":
                v = f"[{c.get('fonte', '?')}|{c.get('confianca', '?')}] {v or ''}".strip()
            ws.cell(i, j).value = v
    saida.parent.mkdir(parents=True, exist_ok=True)
    wb.save(saida)
    return saida


def conciliar(publico: list[dict], cliente: list[dict], campos=("status", "data_deposito", "data_concessao", "jurisdicao")) -> dict:
    """Compara a extração pública com a do cliente por numero_pedido; nada é sobrescrito."""
    p = {c["numero_pedido"]: c for c in publico}
    k = {c["numero_pedido"]: c for c in cliente}
    div = [{"numero_pedido": n, "campo": f, "publico": p[n].get(f), "cliente": k[n].get(f)}
           for n in sorted(p.keys() & k.keys()) for f in campos if k[n].get(f) not in (None, "") and p[n].get(f) != k[n].get(f)]
    return {"apenas_publico": sorted(p.keys() - k.keys()), "apenas_cliente": sorted(k.keys() - p.keys()), "divergencias": div}
