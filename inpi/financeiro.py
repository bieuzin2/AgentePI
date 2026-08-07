"""Financeiro previsivo: projecao de anuidades 12-36 meses agregada por mes x
jurisdicao, e janelas de desistencia estrategica (pedidos nao concedidos
acumulando anuidade) -- plano-v2 Fase 2.

Reusa quadro_global.montar (BR via INPI + exterior via familia INPADOC) em vez
de reimplementar a projecao. Sem R$: o escritorio ainda nao forneceu
custos.yaml, entao a saida e contagem/janela, nao valor monetario.
"""

from __future__ import annotations

from datetime import date

from inpi import quadro_global as qg
from inpi.mcp_app import mcp
from inpi.prazos import _carregar_lote


@mcp.tool()
def financeiro_projecao(cliente: str, meses: int = 12, hoje: str | None = None) -> dict:
    """Projeta anuidades (BR + exterior) dos proximos N meses, agregadas por
    mes x jurisdicao. Municao para previsibilidade de caixa e conversa
    proativa sobre custo de manutencao de portfolio.

    SEM VALORES EM R$: e contagem de anuidades por mes/pais, nao custo -- o
    escritorio ainda nao forneceu a tabela de retribuicoes (custos.yaml). Ver
    quadro_global.exportar para o XLSX linha a linha, com fonte/confianca.

    Args:
        cliente: nome do titular/cliente.
        meses: janela de projecao, 1 a 36.
        hoje: 'AAAA-MM-DD' de referencia; default a data corrente.
    """
    meses = max(1, min(meses, 36))
    d_hoje = date.fromisoformat(hoje) if hoje else date.today()
    d_ate = qg.anu._mais_meses(d_hoje, meses)
    q = qg.montar(cliente, d_ate.isoformat(), d_hoje.isoformat())

    por_mes_pais: dict[str, dict[str, int]] = {}
    for linha in q["linhas"]:
        venc = linha.get("vencimento")
        if not venc:
            continue
        chave_mes = venc[:7]  # AAAA-MM
        bucket = por_mes_pais.setdefault(chave_mes, {})
        bucket[linha["pais"]] = bucket.get(linha["pais"], 0) + 1

    return {
        "cliente": cliente, "de": d_hoje.isoformat(), "ate": d_ate.isoformat(),
        "total_anuidades_com_data": q["com_data"],
        "por_confianca": q["por_confianca"],
        "por_pais": q["por_pais"],
        "por_mes_x_pais": dict(sorted(por_mes_pais.items())),
        "cobertura": q["cobertura"],
        "nota": (
            "Contagem de anuidades por mes, NAO valor em R$ -- sem tabela de "
            "retribuicoes cadastrada. 'calculado' (Brasil) e confiavel; "
            "'estimado' (exterior) e regra transcrita da legislacao, nao "
            "revisada por profissional habilitado. Confira com o associado local."
        ),
    }


@mcp.tool()
def financeiro_janelas_desistencia(cliente: str) -> dict:
    """Pedidos brasileiros AINDA NAO CONCEDIDOS com anuidade em aberto ou
    complementacao devida -- candidatos a conversa de desistencia estrategica
    antes de acumular mais custo num pedido sem decisao de merito.

    USE QUANDO: revisar portfolio para cortar gastos com pedidos de baixa
    prioridade que seguem acumulando anuidade sem concessao nem indeferimento.
    """
    estados, total = _carregar_lote(titular=cliente)
    candidatos = []
    for num, est in estados.items():
        if est["encerrado_em"]:
            continue  # ja encerrado (indeferido/arquivado/extinto), nada a desistir
        vivos = [d for d in est["despachos"] if not d.get("anulado_em")]
        if any(str(d.get("codigo_despacho")) == "9.1" for d in vivos):
            continue  # ja concedido, nao e mais candidato a desistencia de EXAME
        if not (est["anuidades_em_aberto"] or est["anuidades_complementacao"]):
            continue  # em dia, nao e candidato
        candidatos.append({
            "numero_inpi": num,
            "data_deposito": est["data_deposito"].isoformat() if est["data_deposito"] else None,
            "anuidades_em_aberto": est["anuidades_em_aberto"],
            "anuidades_complementacao": est["anuidades_complementacao"],
        })
    candidatos.sort(key=lambda c: c["data_deposito"] or "9999")
    return {
        "cliente": cliente, "casos_no_criterio": total,
        "candidatos_desistencia": len(candidatos),
        "casos": candidatos,
        "nota": (
            "Candidato = pedido em tramite (nao concedido, nao encerrado) com "
            "anuidade notificada como em debito (8.6/21.6/8.11/8.12/24.x) ou "
            "complementacao devida (8.5). Nao e recomendacao automatica -- e "
            "lista de conferencia para o gestor de portfolio decidir, caso a "
            "caso, junto ao cliente."
        ),
    }
