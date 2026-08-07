"""Radar de oposicao EP da carteira (plano de refinamento, Fase F1).

Para os casos EP de um cliente: situacao do European Patent Register e a
JANELA DE OPOSICAO (9 meses da mencao de concessao, art. 99 EPC) -- aberta =
qualquer terceiro ainda pode opor; e o periodo de maior risco pos-concessao.

Limite declarado: so pedidos EP (Register nao cobre outra rota). Quota EPO:
`max_casos` limita a varredura; rodar por cliente sob demanda.
"""

from __future__ import annotations

from datetime import date

from inpi.familia_epo import familia
from inpi.mcp_app import mcp
from inpi.prazos import _carregar_lote
from inpi.titulares import chave_de, resolver
from inpi.vigencia import _membro_ep

MESES_OPOSICAO = 9  # art. 99(1) EPC


def _data(bruta: str | None) -> date | None:
    """'AAAAMMDD' ou 'AAAA-MM-DD' -> date."""
    if not bruta:
        return None
    s = bruta.replace("-", "")[:8]
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, IndexError):
        return None


def _fim_janela(concessao: date) -> date:
    from inpi.anuidades import _mais_meses

    return _mais_meses(concessao, MESES_OPOSICAO)


@mcp.tool()
def carteira_oposicoes_ep(cliente: str, max_casos: int = 20,
                          hoje: str | None = None) -> dict:
    """Situacao de oposicao dos casos EP de um cliente: oposicoes mencionadas
    no Register e janelas de oposicao (9 meses da mencao de concessao) ainda
    abertas.

    USE QUANDO: monitorar risco pos-concessao dos EPs do cliente, ou saber se
    ainda da tempo de opor contra um EP concedido.

    Args:
        cliente: nome do titular/cliente.
        max_casos: teto de casos consultados por chamada (quota EPO).
        hoje: 'AAAA-MM-DD' de referencia; default a data corrente.
    """
    from epo.epo_mcp import epo_register

    max_casos = max(1, min(max_casos, 100))
    d_hoje = date.fromisoformat(hoje) if hoje else date.today()

    estados, _ = _carregar_lote(titular=cliente)
    ativos = [n for n, e in estados.items() if not e["encerrado_em"]]

    consultados, oposicoes, janelas_abertas, sem_ep, falhas = [], [], [], [], []
    for num_br in ativos[:max_casos]:
        fam = familia(num_br)
        ep = _membro_ep(fam.get("membros", []))
        if not ep:
            sem_ep.append(num_br)
            continue
        reg = epo_register(ep["referencia"])
        if reg.get("erro") or not reg.get("encontrado"):
            falhas.append({"numero_inpi": num_br, "membro_ep": ep["referencia"],
                           "motivo": reg.get("mensagem") or reg.get("erro")})
            continue
        item = {
            "numero_inpi": num_br,
            "membro_ep": ep["referencia"],
            "situacao": reg.get("situacao"),
            "situacao_em": reg.get("situacao_em"),
            "mencao_de_concessao": reg.get("mencao_de_concessao"),
        }
        consultados.append(item)

        situacao = (reg.get("situacao") or "").lower()
        # 'No opposition filed within time limit' tambem contem 'opposition' --
        # e justamente o caso BOM. So alerta oposicao afirmativa.
        if "opposition" in situacao and "no opposition" not in situacao:
            oposicoes.append({**item,
                              "nota": "Register menciona oposicao -- confira o dossie EP"})

        conc = _data(reg.get("mencao_de_concessao"))
        if conc:
            fim = _fim_janela(conc)
            if d_hoje <= fim:
                janelas_abertas.append({
                    **item,
                    "janela_ate": fim.isoformat(),
                    "nota": (f"Janela de oposicao (art. 99 EPC) aberta ate {fim.isoformat()}: "
                             "terceiros ainda podem opor contra este EP."),
                })

    return {
        "cliente": cliente,
        "normalizacao": resolver(chave_de(cliente)),
        "fonte": "European Patent Register (EPO OPS)",
        "referencia": d_hoje.isoformat(),
        "casos_ativos": len(ativos),
        "consultados": consultados,
        "oposicoes_mencionadas": oposicoes,
        "janelas_de_oposicao_abertas": janelas_abertas,
        "sem_membro_ep": sem_ep,
        "falhas_de_consulta": falhas,
        "limite_aplicado": max_casos if len(ativos) > max_casos else None,
        "aviso": (
            "So cobre a rota EP. 'situacao' e o texto do Register -- oposicao "
            "so confirmada lendo o dossie. Janela aberta e calculo do art. 99 "
            "EPC sobre a mencao de concessao publicada; nao e docketing."
        ),
    }
