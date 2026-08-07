"""Testes do dossie de cliente (motor de estados mockado)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import inpi.dossie as dz


def _estado(deposito, despachos, encerrado=None):
    return {"data_deposito": deposito, "despachos": despachos,
            "encerrado_em": encerrado}


FAKE = {
    "BR1": _estado(date(2015, 1, 1), [
        {"codigo_despacho": "9.1", "data_rpi": date(2020, 1, 1)}]),
    "BR2": _estado(date(2016, 1, 1), [
        {"codigo_despacho": "9.2", "data_rpi": date(2021, 1, 1)}],
        encerrado=date(2021, 1, 1)),
    "BR3": _estado(date(2022, 1, 1), []),  # pendente
    "BR4": _estado(date(2014, 1, 1), [
        {"codigo_despacho": "9.1", "data_rpi": date(2018, 1, 1)},
        {"codigo_despacho": "9.1", "data_rpi": date(2019, 1, 1), "anulado_em": "x"}]),
}


def test_estatisticas_processos():
    with patch.object(dz, "_carregar_lote", return_value=(FAKE, 4)):
        r = dz._estatisticas_processos("Cliente X")
    assert r["processos"] == 4
    assert r["concedidos"] == 2 and r["indeferidos"] == 1
    assert r["taxa_deferimento"] == round(2 / 3, 3)
    # BR1: 1826 dias; BR4: 1461 (anulado ignorado) -> mediana 1643 (int de 1643.5)
    assert r["dias_ate_concessao_mediana"] == 1643
    assert r["ativos"] == 3


def test_dossie_secao_com_erro_nao_derruba():
    import inpi.financeiro as fin
    import inpi.saude as sau

    with patch.object(dz, "_carregar_lote", side_effect=RuntimeError("banco fora")), \
         patch.object(sau, "carteira_saude", return_value={"score": 80}), \
         patch.object(fin, "financeiro_projecao", return_value={"total_anuidades_com_data": 3}), \
         patch.object(dz, "_geografia", return_value={"por_jurisdicao": {"BR": 2}}):
        r = dz.cliente_dossie("Cliente X")
    assert "banco fora" in r["processos"]["erro"]
    assert r["proveniencia"]["nivel"] == "curada"
    assert r["saude"] == {"score": 80}
    assert r["anuidades"] == {"total_anuidades_com_data": 3}
    assert r["geografia"] == {"por_jurisdicao": {"BR": 2}}
