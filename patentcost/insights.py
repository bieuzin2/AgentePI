"""Monta o arquivo de inteligência patentcost-insights-1 a partir dos casos exportados (agrupados por família)."""
from __future__ import annotations

from datetime import date


def montar_insights(casos: list[dict], cliente: str, fontes: list[dict], lacunas: list[str]) -> dict:
    fams: dict[str, dict] = {}
    for c in casos:
        f = fams.setdefault(c.get("familia") or c["numero_pedido"], {"id": c.get("familia") or c["numero_pedido"], "members": []})
        for k_src, k_dst in (("titulo", "title"), ("ipc_cpc", "ipc"), ("categoria_tecnologica", "section")):
            if c.get(k_src) and not f.get(k_dst):
                f[k_dst] = c[k_src]
        m = {"jurisdiction": c["jurisdicao"], "number": str(c["numero_pedido"]), "status": c.get("status") or "pendente"}
        if c.get("data_deposito"):
            m["filing"] = c["data_deposito"]
        if c.get("data_concessao"):
            m["grant"] = c["data_concessao"]
        m["confidence"] = c.get("confianca") or "inferido"
        f["members"].append(m)
    for f in fams.values():
        dates = sorted(m["filing"] for m in f["members"] if m.get("filing"))
        if dates:
            f["first_filing"] = dates[0]
    return {"format": "patentcost-insights-1", "client": cliente, "generated": date.today().isoformat(),
            "sources": fontes, "families": list(fams.values()), "gaps": lacunas}
