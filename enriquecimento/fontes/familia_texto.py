"""Fallback de reivindicações via família INPADOC + EPO OPS texto integral --
usado quando google_patents.buscar_claims não acha o doc_id BR direto (número
antigo, kind code fora do esperado, etc.).

Por que NÃO fala direto com o PATENTSCOPE: a Fase 0 de descoberta confirmou
que o PATENTSCOPE serve texto integral de membros WO/PCT via páginas JSF com
ViewState (stateful, de sessão) -- funciona no navegador, mas é um protocolo
frágil para replicar num cliente HTTP puro. O EPO OPS (epo_texto_integral)
serve o MESMO texto integral (fonte comum: a publicação WO/EP) por uma API
oficial já integrada neste repo, sem scraping nenhum -- reusar essa tool é
estritamente melhor do que implementar um segundo scraper.

Reusa inpi.familia_epo.familia() (mesma lib/cache que a análise de anuidades
no exterior já usa) em vez de chamar epo_familia_inpadoc direto, para não
duplicar a cascata de formatos de referência que aquele módulo já resolve.
"""

from __future__ import annotations

from enriquecimento.fontes.google_patents import ResultadoClaims, quadro_reivindicatorio

FONTE = "epo_texto_integral"


def buscar_claims_via_familia(numero_normalizado: str) -> ResultadoClaims:
    """Resolve a família INPADOC do número BR e tenta epo_texto_integral para
    cada membro WO/EP, na ordem em que a família os devolve."""
    from epo.epo_mcp import epo_texto_integral
    from inpi.familia_epo import familia

    fam = familia(numero_normalizado)
    if fam.get("erro"):
        return ResultadoClaims(ok=False, doc_id=None, fonte=FONTE,
                                mensagem=f"família INPADOC: {fam['erro']}")

    candidatos = [m for m in fam.get("membros", []) if m.get("pais") in ("WO", "EP")]
    if not candidatos:
        return ResultadoClaims(ok=False, doc_id=None, fonte=FONTE,
                                mensagem="família sem membro WO/EP")

    ultima_msg = "nenhum membro WO/EP tentado"
    for membro in candidatos:
        referencia = membro["referencia"]
        resp = epo_texto_integral(referencia, secao="claims")
        if resp.get("disponivel") and resp.get("texto"):
            return ResultadoClaims(
                ok=True, doc_id=referencia, fonte=FONTE,
                reivindicacoes=quadro_reivindicatorio(resp["texto"]),
            )
        ultima_msg = resp.get("mensagem") or f"{referencia}: sem texto integral"
    return ResultadoClaims(ok=False, doc_id=None, fonte=FONTE, mensagem=ultima_msg)
