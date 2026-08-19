"""Dossie de cliente SOB DEMANDA (Fase E2, reescrito na Fase G).

Antes rodava tudo de uma vez -- inclusive as consultas EPO caras -- e o agente
conversacional muitas vezes ignorava a tool e recompunha na mao, estourando o
timeout de 100s do Copilot Studio. Agora:

  cliente_dossie(cliente)                -> so o MENU de secoes (custo ~zero,
                                            nenhuma query pesada)
  cliente_dossie(cliente, secoes=[...])  -> roda so as secoes pedidas

O menu separa por CUSTO: nucleo (base INPI local, rapido) vs exterior (consulta
EPO, mais lento). Assim o agente pergunta ao usuario o que interessa antes de
gastar tempo/quota. Cada secao declara a propria fonte; erro numa secao vira
{"erro": ...}, nunca derruba as outras.
"""

from __future__ import annotations

from datetime import date
from statistics import median

from inpi.mcp_app import mcp
from inpi.prazos import _carregar_lote

SECOES = {
    "processos_e_anuidades": (
        "RAPIDO (base INPI local + familia INPADOC): contagem de processos, "
        "taxa de deferimento, tempo mediano ate concessao e projecao de "
        "anuidades BR + exterior."
    ),
    "saude": (
        "RAPIDO (base INPI local): score 0-100 do portfolio com os componentes "
        "e as lacunas que explicam o numero."
    ),
    "exterior_epo": (
        "MAIS LENTO (consulta o EPO, respeita quota): vigencia no exterior por "
        "pais -- inclui Acordo de Londres -- e oposicoes/janelas do art. 99 nos EPs."
    ),
    "gaps_protecao_pct": (
        "MAIS LENTO (familia INPADOC + landscape): pedidos PCT perto do prazo de "
        "fase nacional (art. 22/39) e os paises importantes onde o titular ainda "
        "NAO protegeu -- oportunidade proativa de negocio."
    ),
}


def _secao(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except Exception as exc:
        return {"erro": f"{type(exc).__name__}: {exc}"}


def _estatisticas_processos(cliente: str) -> dict:
    """Contagens e taxa de deferimento a partir do motor de estados (base INPI)."""
    estados, total = _carregar_lote(titular=cliente)
    concedidos, indeferidos, dias_concessao, ativos = 0, 0, [], 0
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


def _rodar_secao(cliente: str, nome: str, meses_anuidades: int) -> dict:
    if nome == "processos_e_anuidades":
        from inpi.financeiro import financeiro_projecao
        return {
            "processos": _secao(_estatisticas_processos, cliente),
            "anuidades": _secao(financeiro_projecao, cliente, meses=meses_anuidades),
        }
    if nome == "saude":
        from inpi.saude import carteira_saude
        # score rapido, sem rede -- exterior fica na secao exterior_epo
        return _secao(carteira_saude, cliente, incluir_exterior=False)
    if nome == "exterior_epo":
        from inpi.oposicoes import carteira_oposicoes_ep
        from inpi.vigencia import carteira_auditoria_vigencia
        return {
            "vigencia": _secao(carteira_auditoria_vigencia, cliente),
            "oposicoes": _secao(carteira_oposicoes_ep, cliente),
        }
    if nome == "gaps_protecao_pct":
        from inpi.gaps_protecao import inpi_gaps_protecao
        return _secao(inpi_gaps_protecao, cliente)
    return {"erro": f"secao desconhecida: {nome!r}. Validas: {sorted(SECOES)}"}


@mcp.tool()
def cliente_dossie(cliente: str, secoes: list[str] | None = None,
                   meses_anuidades: int = 12) -> dict:
    """Dossie de cliente SOB DEMANDA. Chamada sem 'secoes' devolve o MENU de
    secoes disponiveis (rapido, nenhuma consulta pesada) -- MOSTRE o menu ao
    usuario e pergunte o que interessa antes de rodar. Chamada com 'secoes'
    roda so o que foi pedido.

    USE QUANDO: o usuario pedir panorama/dossie de um cliente. NAO componha o
    dossie manualmente com varias chamadas de inpi_processo -- use esta tool.

    Args:
        cliente: nome do titular/cliente.
        secoes: lista dentre 'processos_e_anuidades', 'saude', 'exterior_epo'.
            None (default) devolve so o menu.
        meses_anuidades: janela da projecao de anuidades (1 a 36).
    """
    from inpi.titulares import chave_de, resolver

    norm = resolver(chave_de(cliente))
    if not secoes:
        return {
            "cliente": cliente,
            "normalizacao": norm,
            "menu": True,
            "secoes_disponiveis": SECOES,
            "instrucao": (
                "Mostre estas secoes ao usuario e pergunte quais quer ver. Depois "
                "chame cliente_dossie de novo com secoes=[...] so com as escolhidas. "
                "'exterior_epo' consulta o EPO e e mais lento -- confirme antes."
            ),
        }

    invalidas = [s for s in secoes if s not in SECOES]
    if invalidas:
        return {"erro": True,
                "mensagem": f"secoes invalidas {invalidas}. Validas: {sorted(SECOES)}"}

    return {
        "cliente": cliente,
        "gerado_em": date.today().isoformat(),
        "normalizacao": norm,
        "secoes_rodadas": secoes,
        "resultado": {s: _rodar_secao(cliente, s, meses_anuidades) for s in secoes},
        "nota": (
            "Cada secao declara a propria fonte. 'processos_e_anuidades' e 'saude' "
            "saem da base INPI local (+ familia INPADOC); 'exterior_epo' consulta o "
            "EPO. Nada aqui e fatura nem veredito."
        ),
    }
