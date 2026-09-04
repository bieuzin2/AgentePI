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
