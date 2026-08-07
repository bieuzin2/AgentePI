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


def _patch_titular(nivel="curada"):
    return patch.multiple(
        "inpi.titulares",
        chave_de=lambda nome: "CHAVE",
        resolver=lambda chave: {"nivel": nivel, "chave": chave},
    )


def test_sem_secoes_devolve_so_o_menu():
    # menu nao pode rodar nenhuma query pesada
    with patch.object(dz, "_carregar_lote") as carregar, _patch_titular():
        r = dz.cliente_dossie("Cliente X")
    carregar.assert_not_called()
    assert r["menu"] is True
    assert set(r["secoes_disponiveis"]) == {
        "processos_e_anuidades", "saude", "exterior_epo"}
    assert r["normalizacao"]["nivel"] == "curada"


def test_secao_com_erro_nao_derruba_as_outras():
    import inpi.financeiro as fin

    with patch.object(dz, "_carregar_lote", side_effect=RuntimeError("banco fora")), \
         patch.object(fin, "financeiro_projecao",
                      return_value={"total_anuidades_com_data": 3}), \
         _patch_titular():
        r = dz.cliente_dossie("Cliente X", secoes=["processos_e_anuidades"])
    secao = r["resultado"]["processos_e_anuidades"]
    assert "banco fora" in secao["processos"]["erro"]
    assert secao["anuidades"] == {"total_anuidades_com_data": 3}
    assert r["secoes_rodadas"] == ["processos_e_anuidades"]


def test_secao_invalida_e_erro():
    with _patch_titular():
        r = dz.cliente_dossie("Cliente X", secoes=["inventada"])
    assert r["erro"] is True and "inventada" in r["mensagem"]


def test_so_roda_secoes_pedidas():
    with patch.object(dz, "_rodar_secao", return_value={"ok": 1}) as run, _patch_titular():
        r = dz.cliente_dossie("Cliente X", secoes=["saude"])
    run.assert_called_once()
    assert list(r["resultado"]) == ["saude"]
