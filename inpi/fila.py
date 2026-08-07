"""Fila de trabalho semanal: tudo que vence em N dias, todas as carteiras
(plano de refinamento, Fase E3).

Consolida anuidades BR + exterior (quadro_global.montar, que ja carrega
confianca por linha) e tarefas internas com prazo. Ordenado por vencimento.
`criar_tarefas=True` reusa tarefas.tarefa_criar, com dedup por descricao.
"""

from __future__ import annotations

from datetime import date, timedelta

from inpi import quadro_global as qg
from inpi import tarefas
from inpi.mcp_app import mcp


def _clientes_curados() -> list[str]:
    """Nomes de exibicao dos clientes curados (Fase A, clientes-clarke.csv).
    Base padrao da fila -- substitui a antiga varredura da tabela `casos`."""
    from inpi.titulares import _clientes

    return sorted(_clientes().values())


@mcp.tool()
def fila_semana(dias: int = 30, criar_tarefas: bool = False,
                hoje: str | None = None, clientes: list[str] | None = None) -> dict:
    """Fila de trabalho consolidada: anuidades (BR + exterior) dos clientes
    curados que vencem na janela, mais tarefas internas com prazo. Ordenada
    por vencimento.

    USE QUANDO: planejar a semana/mes do escritorio ("o que vence ate dia X?")
    sem perguntar cliente por cliente.

    Args:
        dias: janela em dias (1 a 120).
        criar_tarefas: True cria lembrete interno para cada vencimento ainda
            sem tarefa aberta equivalente (dedup por descricao).
        hoje: 'AAAA-MM-DD' de referencia; default a data corrente.
        clientes: lista de titulares a varrer; default = clientes curados
            (Fase A). Passe nomes explicitos para rodar num titular avulso.
    """
    dias = max(1, min(dias, 120))
    d_hoje = date.fromisoformat(hoje) if hoje else date.today()
    d_ate = d_hoje + timedelta(days=dias)

    clientes_informados = bool(clientes)
    clientes = clientes if clientes else _clientes_curados()
    itens: list[dict] = []
    falhas: list[dict] = []
    for cliente in clientes:
        try:
            q = qg.montar(cliente, d_ate.isoformat(), d_hoje.isoformat())
        except Exception as exc:  # um cliente com erro nao pode sumir com a fila
            falhas.append({"cliente": cliente,
                           "erro": f"{type(exc).__name__}: {exc}"})
            continue
        for l in q["linhas"]:
            if not l.get("vencimento"):
                continue
            itens.append({
                "tipo": "anuidade",
                "cliente": cliente,
                "numero_oficial": l["numero_oficial"],
                "pais": l["pais"],
                "descricao": l["anuidade"],
                "vencimento": l["vencimento"],
                "fim_com_graca": l.get("fim_com_graca"),
                "confianca": l["confianca"],
                "fonte": l["fonte"],
            })

    for t in tarefas.tarefas_vencendo(dias=dias, hoje=d_hoje.isoformat()):
        itens.append({
            "tipo": "tarefa_interna",
            "cliente": None,
            "numero_oficial": t.get("processo"),
            "pais": None,
            "descricao": t["descricao"],
            "vencimento": str(t["prazo_interno"]),
            "confianca": "tarefa interna",
            "fonte": "tarefas do escritorio",
            "tarefa_id": t["id"],
        })

    itens.sort(key=lambda i: (i["vencimento"], i["cliente"] or "",
                              i["numero_oficial"] or ""))

    criadas = []
    if criar_tarefas:
        abertas = {t["descricao"] for t in tarefas.tarefa_listar()["lista"]}
        for i in itens:
            if i["tipo"] != "anuidade":
                continue
            desc = (f"[fila] {i['descricao']} de {i['numero_oficial']} "
                    f"({i['cliente']}) vence {i['vencimento']}")
            if desc in abertas:
                continue
            r = tarefas.tarefa_criar(desc, processo=i["numero_oficial"],
                                     prazo_interno=i["vencimento"])
            criadas.append({"id": r["id"], "descricao": desc})

    return {
        "de": d_hoje.isoformat(), "ate": d_ate.isoformat(),
        "base_de_clientes": ("titulares informados na chamada" if clientes_informados
                             else "clientes curados (Clarke Modet)"),
        "clientes_varridos": len(clientes),
        "clientes_com_falha": falhas,
        "total_itens": len(itens),
        "por_confianca": {
            c: sum(1 for i in itens if i["confianca"] == c)
            for c in sorted({i["confianca"] for i in itens})
        },
        "itens": itens,
        "tarefas_criadas": criadas,
        "nota": (
            "Anuidade e projecao, nao fatura -- a base nao sabe o que ja foi "
            "pago. 'estimado' (exterior) exige confirmacao com o associado "
            "local. Tarefa interna e lembrete livre, nao prazo legal."
        ),
    }
