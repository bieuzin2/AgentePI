"""Dossie de cliente em UMA chamada (plano de refinamento, Fase E2).

Levantamento estatistico completo do cliente compondo o que ja existe --
nenhuma logica de negocio nova. Cada secao declara a propria fonte; o que
falhar vira {"erro": ...} na secao, nunca derruba o dossie inteiro.
"""

from __future__ import annotations

from datetime import date
from statistics import median

from inpi.mcp_app import mcp
from inpi.prazos import _carregar_lote
from inpi.titulares import PROVENIENCIA_CARTEIRA


def _secao(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except Exception as exc:
        return {"erro": f"{type(exc).__name__}: {exc}"}


def _estatisticas_processos(cliente: str) -> dict:
    """Contagens e taxa de deferimento a partir do motor de estados."""
    estados, total = _carregar_lote(titular=cliente)
    concedidos, indeferidos, dias_concessao = 0, 0, []
    ativos = 0
    for est in estados.values():
        vivos = [d for d in est["despachos"] if not d.get("anulado_em")]
        codigos = {str(d.get("codigo_despacho")) for d in vivos}
        if "9.1" in codigos:
            concedidos += 1
            if est["data_deposito"]:
                d91 = min(d["data_rpi"] for d in vivos
                          if str(d.get("codigo_despacho")) == "9.1")
                dias_concessao.append((d91 - est["data_deposito"]).days)
        elif "9.2" in codigos:
            indeferidos += 1
        if not est["encerrado_em"]:
            ativos += 1
    decididos = concedidos + indeferidos
    return {
        "fonte": "base INPI local (despachos)",
        "processos": total,
        "ativos": ativos,
        "concedidos": concedidos,
        "indeferidos": indeferidos,
        "taxa_deferimento": round(concedidos / decididos, 3) if decididos else None,
        "dias_ate_concessao_mediana": int(median(dias_concessao)) if dias_concessao else None,
        "nota": "taxa sobre casos ja decididos (9.1 vs 9.2); pendentes fora do denominador",
    }


def _geografia(cliente: str) -> dict:
    """Dispersao por jurisdicao da carteira ingerida -- sem chamada EPO."""
    from inpi.carteira import BANCO, conectar_carteira

    c = conectar_carteira(BANCO, read_only=True)
    try:
        linhas = c.execute(
            "SELECT jurisdicao, count(*) FROM casos WHERE cliente = ? "
            "GROUP BY 1 ORDER BY 2 DESC", [cliente]).fetchall()
    finally:
        c.close()
    return {"fonte": "carteira ingerida",
            "por_jurisdicao": {j: n for j, n in linhas}}


@mcp.tool()
def cliente_dossie(cliente: str, meses_anuidades: int = 12) -> dict:
    """Dossie completo do cliente em uma chamada: processos e taxa de
    deferimento, tempo mediano ate concessao, saude da carteira, projecao de
    anuidades e dispersao geografica.

    USE QUANDO: preparar reuniao de cliente ou responder "me da um panorama
    do cliente X" -- substitui 5 perguntas separadas.

    Args:
        cliente: nome do titular/cliente.
        meses_anuidades: janela da projecao de anuidades (1 a 36).
    """
    from inpi.financeiro import financeiro_projecao
    from inpi.saude import carteira_saude

    return {
        "cliente": cliente,
        "gerado_em": date.today().isoformat(),
        "proveniencia": PROVENIENCIA_CARTEIRA,
        "processos": _secao(_estatisticas_processos, cliente),
        "saude": _secao(carteira_saude, cliente),
        "anuidades": _secao(financeiro_projecao, cliente, meses=meses_anuidades),
        "geografia": _secao(_geografia, cliente),
        "nota": (
            "Cada secao declara a propria fonte. 'saude' e 'geografia' dependem "
            "da carteira ingerida; 'processos' e 'anuidades' saem da base INPI "
            "(+ familia INPADOC no exterior). Nada aqui e fatura nem veredito."
        ),
    }
