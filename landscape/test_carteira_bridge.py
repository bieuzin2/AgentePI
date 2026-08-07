"""Testes de landscape/carteira_bridge.py -- bancos sinteticos (nao a base
real) e _rodar mockado para landscape_carteira, sem rede/BigQuery."""

from pathlib import Path

import duckdb
import pytest

from landscape import carteira_bridge as cb


@pytest.fixture
def bancos(tmp_path, monkeypatch):
    banco_carteira = tmp_path / "carteira.duckdb"
    con = duckdb.connect(str(banco_carteira))
    con.execute("CREATE TABLE casos (cliente VARCHAR, jurisdicao VARCHAR, numero_norm VARCHAR)")
    con.execute("INSERT INTO casos VALUES ('Cliente X', 'BR', '111'), "
                "('Cliente X', 'BR', '222'), ('Cliente X', 'US', '333')")
    con.close()

    banco_inpi = tmp_path / "inpi.duckdb"
    con = duckdb.connect(str(banco_inpi))
    con.execute("CREATE TABLE ipc (numero_inpi VARCHAR, simbolo VARCHAR)")
    con.execute("INSERT INTO ipc VALUES "
                "('111', 'A61K31/00'), ('111', 'A61K9/00'), ('222', 'A61K47/00'), "
                "('222', 'B65D1/00')")
    con.close()

    monkeypatch.setattr(cb, "BANCO_CARTEIRA", banco_carteira)
    monkeypatch.setattr(cb, "BANCO_INPI", banco_inpi)


def test_cpcs_da_carteira_agrega_por_subclasse(bancos):
    r = cb.cpcs_da_carteira("Cliente X", top=1)
    assert r["casos_br_na_carteira"] == 2
    assert r["top_cpc"] == ["A61K"]  # 3 ocorrencias vs B65D 1, so o top 1 pedido
    assert r["distribuicao"]["A61K"] == 3
    assert r["distribuicao"]["B65D"] == 1


def test_cpcs_da_carteira_sem_casos_br_falha_alto(bancos):
    r = cb.cpcs_da_carteira("Cliente Inexistente")
    assert r["erro"] is True


def test_landscape_carteira_compoe_por_cpc(bancos, monkeypatch):
    chamadas = []

    def _rodar_fake(nome, fn, args, **kw):
        chamadas.append((nome, args["cpc_prefix"]))
        return {"linhas": [{"cpc": args["cpc_prefix"]}], "cache": False}

    monkeypatch.setattr(cb, "_rodar", _rodar_fake)
    r = cb.landscape_carteira("Cliente X", top_cpc=1)
    assert r["top_cpc_da_carteira"] == ["A61K"]
    assert "A61K" in r["por_cpc"]
    assert r["por_cpc"]["A61K"]["casos_da_carteira_nesse_cpc"] == 3
    assert len(chamadas) == 2  # top_titulares + evolucao_temporal, 1 cpc so


def test_landscape_carteira_propaga_erro_de_cpcs(bancos):
    r = cb.landscape_carteira("Cliente Inexistente")
    assert r["erro"] is True
