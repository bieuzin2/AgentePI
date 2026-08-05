"""Testes de inpi/tarefas.py -- criar/listar/concluir e o recorte de vencimento
usado pelo dashboard. Sem rede."""

import pytest

from inpi import tarefas as tf


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(tf, "BANCO", tmp_path / "carteira.duckdb")


def test_criar_lista_e_conclui(banco):
    r = tf.tarefa_criar("responder oficio", processo="BR102022010731",
                         prazo_interno="2026-08-10")
    assert r["origem"] == tf._ORIGEM
    tid = r["id"]

    lista = tf.tarefa_listar()["lista"]
    assert len(lista) == 1
    assert lista[0]["descricao"] == "responder oficio"
    assert lista[0]["status"] == "aberta"

    ok = tf.tarefa_concluir(tid)
    assert ok["ok"] is True
    assert tf.tarefa_listar()["lista"] == []
    assert len(tf.tarefa_listar(status="todas")["lista"]) == 1


def test_concluir_id_inexistente(banco):
    r = tf.tarefa_concluir(999)
    assert r["ok"] is False


def test_listar_filtra_por_processo(banco):
    tf.tarefa_criar("a", processo="P1")
    tf.tarefa_criar("b", processo="P2")
    assert len(tf.tarefa_listar(processo="P1")["lista"]) == 1


def test_tarefas_vencendo_janela_7_dias(banco):
    tf.tarefa_criar("vence logo", prazo_interno="2026-08-10")
    tf.tarefa_criar("vence longe", prazo_interno="2026-09-30")
    tf.tarefa_criar("sem prazo")

    venc = tf.tarefas_vencendo(dias=7, hoje="2026-08-05")
    assert len(venc) == 1
    assert venc[0]["descricao"] == "vence logo"


def test_tarefas_vencendo_banco_inexistente(tmp_path, monkeypatch):
    monkeypatch.setattr(tf, "BANCO", tmp_path / "nao-existe.duckdb")
    assert tf.tarefas_vencendo() == []
