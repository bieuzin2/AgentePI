"""Testes de inpi/radar.py -- watermark contra a base real do INPI (leitura
pura, sem rede), banco de watermark/tarefas em arquivo temporario."""

import pytest

from inpi import radar
from inpi import tarefas as tf


@pytest.fixture
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "carteira.duckdb"
    monkeypatch.setattr(radar, "BANCO_TAREFAS", caminho)
    monkeypatch.setattr(tf, "BANCO", caminho)


def test_primeira_rodada_traz_historico_e_avanca_watermark(banco):
    r1 = radar.inpi_radar("Clarke Modet", ipc="A61K 31/57", min_pedidos=1)
    assert r1["rodada_anterior_ate_rpi"] == 0
    assert r1["titulares_novos"] > 0
    assert r1["rodada_atual_ate_rpi"] > 0


def test_segunda_rodada_sem_novidade_e_vazia(banco):
    r1 = radar.inpi_radar("Clarke Modet", ipc="A61K 31/57", min_pedidos=1)
    r2 = radar.inpi_radar("Clarke Modet", ipc="A61K 31/57", min_pedidos=1)
    assert r2["rodada_anterior_ate_rpi"] == r1["rodada_atual_ate_rpi"]
    assert r2["titulares_novos"] == 0


def test_criar_tarefas_grava_uma_por_titular(banco):
    r1 = radar.inpi_radar("Clarke Modet", ipc="A61K 31/57", min_pedidos=1,
                          criar_tarefas=True)
    assert len(r1["tarefas_criadas"]) == r1["titulares_novos"]
    lista = tf.tarefa_listar()["lista"]
    assert len(lista) == r1["titulares_novos"]


def test_radares_de_ipc_diferente_tem_watermark_independente(banco):
    radar.inpi_radar("Clarke Modet", ipc="A61K 31/57", min_pedidos=1)
    r_outro = radar.inpi_radar("Clarke Modet", ipc="H01L", min_pedidos=100)
    assert r_outro["rodada_anterior_ate_rpi"] == 0
