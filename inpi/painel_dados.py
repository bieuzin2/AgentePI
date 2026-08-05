"""Camada de dados do dashboard do escritorio (docs/plano-v2.md 4.3).

Uma funcao publica: montar(procurador, hoje, banco_alertas). Devolve o dict
que o render (HTML hoje) consome direto, sem tocar o banco de novo.

Reusa panorama_carteira.panorama() para tudo que ja existia (situacao, IPC,
clientes, prazos 12m -- inclusive anuidades, ja projetadas). Acrescenta as
secoes novas do dashboard (plano 4.3):
  - alertas_semana: ultimos alertas gravados por vigilancia/executar.py
  - anuidades_90d: recorte do prazos_12m ja calculado, so anuidade <= 90 dias
  - tarefas: lembretes internos abertos (inpi/tarefas.py, plano 4.7) + recorte
    dos que vencem em 7 dias -- lido direto da tabela, sem vigia novo (tarefa
    leve nao justifica inflar o pacote vigilancia)
  - landscape: placeholder -- graficos de landscape sao Fase 5 (plano 4.6)

Os relatorios de prazos (inpi/relatorios.py, PDF/XLSX) NAO usam esta camada:
respondem a um recorte de datas arbitrario (--de/--ate escolhidos na hora),
nao ao snapshot fixo do dia que o dashboard mostra. Forcar os dois no mesmo
dict seria inventar uma abstracao para dados que nao tem o mesmo formato.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from inpi import panorama_carteira as pc
from inpi import tarefas as tf

_COLUNAS_ALERTA = ["tipo", "severidade", "processo", "titular", "mensagem",
                    "data", "fonte", "data_corte", "criado_em"]


def _alertas_semana(banco_alertas: Path | None, limite: int = 30) -> list[dict]:
    """Ultimos alertas gravados pela vigilancia. [] se o banco ainda nao existe
    (o dashboard tem que abrir mesmo antes da primeira execucao agendada)."""
    if banco_alertas is None:
        from vigilancia.executar import BANCO as banco_alertas
    if not banco_alertas.exists():
        return []
    import duckdb
    con = duckdb.connect(str(banco_alertas), read_only=True)
    try:
        linhas = con.execute(
            f"SELECT {', '.join(_COLUNAS_ALERTA)} FROM alertas "
            "ORDER BY criado_em DESC LIMIT ?",
            [limite],
        ).fetchall()
    finally:
        con.close()
    return [dict(zip(_COLUNAS_ALERTA, linha)) for linha in linhas]


def _anuidades_90d(prazos_12m: dict, ref: date) -> list[dict]:
    """Recorte dos prazos ja projetados por panorama(): so anuidade, <=90 dias.
    Nao reconsulta o banco -- panorama() ja projetou os 12 meses inteiros."""
    limite = (ref + timedelta(days=90)).isoformat()
    return sorted(
        (p for p in prazos_12m["lista"]
         if p["tipo"] == "anuidade" and p["prazo"] <= limite),
        key=lambda p: p["prazo"],
    )


def montar(procurador: str = "Clarke Modet", hoje: str | None = None,
           banco_alertas: Path | None = None) -> dict:
    """Painel completo do escritorio: panorama + alertas + anuidades 90 dias.

    `landscape` fica como placeholder ate a Fase 5 do plano.
    """
    ref = date.fromisoformat(hoje) if hoje else date.today()
    d = pc.panorama(procurador, hoje=ref.isoformat())
    d["alertas_semana"] = _alertas_semana(banco_alertas)
    d["anuidades_90d"] = _anuidades_90d(d["prazos_12m"], ref)
    d["tarefas"] = {
        "lista": tf.tarefa_listar(status="aberta")["lista"],
        "vencendo_7d": tf.tarefas_vencendo(dias=7, hoje=ref.isoformat()),
        "nota": "Lembrete interno, não é prazo legal (não é docketing).",
    }
    d["landscape"] = {
        "nota": "Graficos de landscape ainda nao implementados (Fase 5, "
                "plano 4.6 -- TODO).",
    }
    return d


def demo() -> None:
    """Self-check: as 4 secoes novas existem e tem o formato esperado."""
    d = montar("Clarke Modet", hoje="2026-08-04")
    assert isinstance(d["alertas_semana"], list)
    assert isinstance(d["anuidades_90d"], list)
    assert all(p["tipo"] == "anuidade" for p in d["anuidades_90d"])
    assert d["tarefas"]["lista"] == []
    assert "nota" in d["landscape"]
    print(f"OK  alertas={len(d['alertas_semana'])}  anuidades_90d={len(d['anuidades_90d'])}")


if __name__ == "__main__":
    demo()
