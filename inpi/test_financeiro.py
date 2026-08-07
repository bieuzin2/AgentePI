"""Testes de inpi/financeiro.py -- smoke test contra a base real (mesmo padrao
de test_inpi_mcp.py e test_gargalos.py: base local ja presente, sem rede para
o Brasil; um teste marcado 'online' cobre a chamada real ao EPO)."""

import pytest

from inpi import financeiro as fin


def test_janelas_desistencia_exige_titular_valido():
    r = fin.financeiro_janelas_desistencia("APTAR")
    assert r["casos_no_criterio"] > 0
    assert r["candidatos_desistencia"] == len(r["casos"])


def test_janelas_desistencia_titular_com_candidatos():
    r = fin.financeiro_janelas_desistencia("Petrobras")
    assert r["candidatos_desistencia"] > 0
    for caso in r["casos"]:
        assert caso["anuidades_em_aberto"] or caso["anuidades_complementacao"]


def test_janelas_desistencia_titular_inexistente():
    r = fin.financeiro_janelas_desistencia("TITULAR QUE NAO EXISTE XYZ 123")
    assert r["casos_no_criterio"] == 0
    assert r["candidatos_desistencia"] == 0


@pytest.mark.online
def test_projecao_agrega_por_mes_x_pais():
    r = fin.financeiro_projecao("APTAR ITALIA S.P.A.", meses=12)
    assert r["por_pais"]["BR"] > 0
    total_agregado = sum(sum(v.values()) for v in r["por_mes_x_pais"].values())
    assert total_agregado == r["total_anuidades_com_data"]
    assert "cobertura" in r
