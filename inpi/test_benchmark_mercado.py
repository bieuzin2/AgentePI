"""Testes de inpi_benchmark_mercado contra um banco DuckDB minimo em memoria."""

from __future__ import annotations

import duckdb
import pytest

import inpi.benchmark_mercado as bm


@pytest.fixture
def con(monkeypatch):
    c = duckdb.connect()
    c.execute("CREATE TABLE procuradores (numero_inpi VARCHAR, procurador VARCHAR)")
    c.execute("CREATE TABLE escritorios (original VARCHAR, chave VARCHAR)")
    c.execute("CREATE TABLE ipc (numero_inpi VARCHAR, simbolo VARCHAR)")
    c.execute("CREATE TABLE biblio (numero_inpi VARCHAR, data_deposito VARCHAR)")
    c.execute("CREATE TABLE ipc_campo_tecnologico (ipc_subclasse VARCHAR, campo_tecnologico VARCHAR)")
    c.execute("CREATE TABLE estatistica_nacional (ano INTEGER, campo_tecnologico VARCHAR, depositos INTEGER, concessoes INTEGER)")

    c.execute("INSERT INTO procuradores VALUES ('P1', 'CLARKE MODET'), ('P2', 'CLARKE MODET')")
    c.execute("INSERT INTO escritorios VALUES ('CLARKE MODET', 'CLARKE MODET')")
    c.execute("INSERT INTO ipc VALUES ('P1', 'A61K0031'), ('P2', 'A61K0009')")
    c.execute("INSERT INTO biblio VALUES ('P1', '2023-05-01'), ('P2', '2023-06-01')")
    c.execute("INSERT INTO ipc_campo_tecnologico VALUES ('A61K', 'Farmacêutica')")
    c.execute("INSERT INTO estatistica_nacional VALUES (2023, 'Farmacêutica', 1000, 400)")

    def _linhas(sql, params=()):
        cur = c.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    monkeypatch.setattr(bm, "_linhas", _linhas)
    monkeypatch.setattr(bm, "_tem_tabela", lambda nome: True)
    return c


def test_benchmark_mercado_compara_carteira_com_nacional(con):
    r = bm.inpi_benchmark_mercado("CLARKE MODET", ano_inicial=2023, ano_final=2023,
                                  campo_tecnologico="Farmacêutica")

    assert r["carteira"]["depositos"] == 2
    assert r["nacional"]["depositos"] == 1000
    assert r["share_mercado_pct"] == pytest.approx(0.2)


def test_benchmark_mercado_sem_estatistica_nacional_avisa(con, monkeypatch):
    monkeypatch.setattr(bm, "_tem_tabela", lambda nome: nome != "estatistica_nacional")
    r = bm.inpi_benchmark_mercado("CLARKE MODET")
    assert r["erro"] is True
