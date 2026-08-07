"""Testes da fila de trabalho semanal (quadro_global e tarefas mockados)."""

from __future__ import annotations

from unittest.mock import patch

import inpi.fila as fila


QUADRO = {
    "linhas": [
        {"numero_oficial": "BR 1", "pais": "BR", "anuidade": "5a anuidade",
         "vencimento": "2026-08-20", "fim_com_graca": "2027-02-20",
         "confianca": "calculado", "fonte": "INPI"},
        {"numero_oficial": "EP-1-B1", "pais": "DE", "anuidade": "—",
         "vencimento": None, "confianca": "indisponivel", "fonte": "x"},
    ]
}


def test_fila_consolida_e_ordena():
    with patch.object(fila, "_clientes_curados", return_value=["A", "B"]), \
         patch.object(fila.qg, "montar", return_value=QUADRO), \
         patch.object(fila.tarefas, "tarefas_vencendo", return_value=[
             {"id": 7, "processo": None, "descricao": "ligar associado",
              "prazo_interno": "2026-08-10"}]):
        r = fila.fila_semana(dias=30, hoje="2026-08-07")

    assert r["clientes_varridos"] == 2
    # linha sem vencimento fora; 2 clientes x 1 anuidade + 1 tarefa = 3
    assert r["total_itens"] == 3
    assert r["itens"][0]["tipo"] == "tarefa_interna"  # vence antes
    assert r["itens"][0]["vencimento"] == "2026-08-10"
    assert r["tarefas_criadas"] == []


def test_fila_cliente_com_falha_nao_some_com_o_resto():
    def montar(cliente, ate, hoje):
        if cliente == "B":
            raise RuntimeError("EPO fora")
        return QUADRO

    with patch.object(fila, "_clientes_curados", return_value=["A", "B"]), \
         patch.object(fila.qg, "montar", side_effect=montar), \
         patch.object(fila.tarefas, "tarefas_vencendo", return_value=[]):
        r = fila.fila_semana(dias=30, hoje="2026-08-07")

    assert r["total_itens"] == 1
    assert r["clientes_com_falha"][0]["cliente"] == "B"


def test_criar_tarefas_com_dedup():
    ja_existe = ("[fila] 5a anuidade de BR 1 (A) vence 2026-08-20")
    with patch.object(fila, "_clientes_curados", return_value=["A"]), \
         patch.object(fila.qg, "montar", return_value=QUADRO), \
         patch.object(fila.tarefas, "tarefas_vencendo", return_value=[]), \
         patch.object(fila.tarefas, "tarefa_listar",
                      return_value={"lista": [{"descricao": ja_existe}]}), \
         patch.object(fila.tarefas, "tarefa_criar") as criar:
        r = fila.fila_semana(dias=30, criar_tarefas=True, hoje="2026-08-07")

    criar.assert_not_called()  # dedup: tarefa identica ja aberta
    assert r["tarefas_criadas"] == []


def test_clientes_override_ignora_lista_curada():
    with patch.object(fila, "_clientes_curados",
                      side_effect=AssertionError("nao deveria ler a lista curada")), \
         patch.object(fila.qg, "montar", return_value={"linhas": []}), \
         patch.object(fila.tarefas, "tarefas_vencendo", return_value=[]):
        r = fila.fila_semana(dias=30, hoje="2026-08-07", clientes=["Titular Avulso"])
    assert r["clientes_varridos"] == 1
    assert r["base_de_clientes"] == "titulares informados na chamada"
