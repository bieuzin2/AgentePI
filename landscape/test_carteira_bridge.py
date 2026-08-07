"""Testes de landscape/carteira_bridge.py -- banco INPI sintetico com
depositantes/titulares/ipc (titular real, sem tabela `casos`); _rodar mockado
para landscape_carteira, sem rede/BigQuery."""

import duckdb
import pytest

from landscape import carteira_bridge as cb


@pytest.fixture
def banco_inpi(tmp_path, monkeypatch):
    banco = tmp_path / "inpi.duckdb"
    con = duckdb.connect(str(banco))
    con.execute("CREATE TABLE depositantes (numero_inpi VARCHAR, depositante VARCHAR)")
    con.execute("INSERT INTO depositantes VALUES "
                "('111','CLIENTE X LTDA'), ('222','CLIENTE X LTDA')")
    con.execute("CREATE TABLE titulares (original VARCHAR, chave VARCHAR)")
    con.execute("INSERT INTO titulares VALUES ('CLIENTE X LTDA','CLIENTE X')")
    con.execute("CREATE TABLE ipc (numero_inpi VARCHAR, simbolo VARCHAR)")
    con.execute("INSERT INTO ipc VALUES "
                "('111','A61K31/00'), ('111','A61K9/00'), "
                "('222','A61K47/00'), ('222','B65D1/00')")
    con.close()
    monkeypatch.setattr(cb, "BANCO_INPI", banco)
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)


def test_cpcs_do_titular_agrega_por_subclasse(banco_inpi):
    r = cb.cpcs_da_carteira("Cliente X", top=1)
    assert r["chave_titular"] == "CLIENTE X"
    assert r["top_cpc"] == ["A61K"]  # 3 ocorrencias vs B65D 1
    assert r["distribuicao"]["A61K"] == 3
    assert r["distribuicao"]["B65D"] == 1


def test_cpcs_titular_inexistente_falha_alto(banco_inpi):
    r = cb.cpcs_da_carteira("Titular Inexistente")
    assert r["erro"] is True


def test_landscape_carteira_compoe_por_cpc(banco_inpi, monkeypatch):
    chamadas = []

    def _rodar_fake(nome, fn, args, **kw):
        chamadas.append((nome, args["cpc_prefix"]))
        return {"linhas": [{"cpc": args["cpc_prefix"]}], "cache": False}

    monkeypatch.setattr(cb, "_rodar", _rodar_fake)
    r = cb.landscape_carteira("Cliente X", top_cpc=1)
    assert r["top_cpc_do_titular"] == ["A61K"]
    assert r["por_cpc"]["A61K"]["processos_do_titular_nesse_cpc"] == 3
    assert len(chamadas) == 2  # top_titulares + evolucao_temporal, 1 cpc so


def test_landscape_carteira_propaga_erro(banco_inpi):
    r = cb.landscape_carteira("Titular Inexistente")
    assert r["erro"] is True
