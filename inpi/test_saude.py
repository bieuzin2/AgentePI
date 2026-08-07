"""Testes de inpi/saude.py -- carteira populada em banco temporario a partir
da base real do INPI (descobrir_inpi e leitura pura de DB, sem rede)."""

import pytest

from inpi import carteira as ct
from inpi import saude as sd


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "BANCO", tmp_path / "carteira.duckdb")


def test_carteira_vazia_e_erro_nao_zero(banco):
    r = sd.carteira_saude("CLIENTE SEM CARTEIRA")
    assert r["erro"] is True


def test_carteira_sem_banco_ainda_e_erro(banco):
    r = sd.carteira_saude("QUALQUER")
    assert r["erro"] is True


def test_score_soma_os_quatro_componentes(banco):
    ct.descobrir_inpi("Cliente", titular="APTAR")
    r = sd.carteira_saude("Cliente")
    soma = sum(c["pontos"] for c in r["componentes"].values())
    assert r["score"] == round(soma, 1)
    assert 0 <= r["score"] <= 100


def test_carteira_so_br_penaliza_cobertura_geografica(banco):
    ct.descobrir_inpi("Cliente", titular="APTAR")
    r = sd.carteira_saude("Cliente")
    assert r["componentes"]["cobertura_geografica"]["jurisdicoes_distintas"] == 1
    assert "concentrada numa unica jurisdicao" in " ".join(r["lacunas"])


def test_componentes_nunca_excedem_o_teto(banco):
    ct.descobrir_inpi("Cliente", titular="APTAR")
    r = sd.carteira_saude("Cliente")
    for comp in r["componentes"].values():
        assert comp["pontos"] <= comp["de"]
