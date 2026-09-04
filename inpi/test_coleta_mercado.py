"""Testes de inpi/coleta_mercado.py com cliente/fila mockados -- sem rede."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import inpi.coleta_mercado as mod


def test_deve_parar_acima_do_limiar():
    resumo = {"erros": 16}
    assert mod.deve_parar(resumo, tamanho_lote=50, limiar=0.3) is True


def test_deve_parar_abaixo_do_limiar():
    resumo = {"erros": 5}
    assert mod.deve_parar(resumo, tamanho_lote=50, limiar=0.3) is False


def test_deve_parar_lote_vazio_nunca_para():
    assert mod.deve_parar({"erros": 0}, tamanho_lote=0, limiar=0.3) is False


def test_processar_lote_marca_sucesso_e_erro_na_fila():
    cliente = MagicMock()
    with patch("inpi.coleta_mercado.coletar_com_fallback_pepi",
               return_value={"registrados": 1, "erros": 1}) as mock_coletar, \
         patch("inpi.coleta_mercado._coletados", return_value={"P1"}), \
         patch("inpi.coleta_mercado.marcar") as mock_marcar:
        resumo = mod.processar_lote(cliente, ["P1", "P2"])

    mock_coletar.assert_called_once_with(cliente, ["P1", "P2"], escritorio_canonico=None)
    mock_marcar.assert_any_call(["P1"], "coletado")
    mock_marcar.assert_any_call(["P2"], "erro")
    assert resumo == {"registrados": 1, "erros": 1}
