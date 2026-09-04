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


def test_rodar_loop_sem_credencial_nao_tenta_rede(monkeypatch, capsys):
    monkeypatch.delenv("INPI_PAG_LOGIN_MERCADO", raising=False)
    monkeypatch.delenv("INPI_PAG_PASSWORD_MERCADO", raising=False)

    with patch("inpi.coleta_mercado.ClientePlataformaNova") as mock_cliente:
        mod.rodar_loop()

    mock_cliente.assert_not_called()
    assert "INPI_PAG_LOGIN_MERCADO" in capsys.readouterr().out


def test_rodar_loop_para_quando_fila_vazia(monkeypatch, capsys):
    monkeypatch.setenv("INPI_PAG_LOGIN_MERCADO", "user")
    monkeypatch.setenv("INPI_PAG_PASSWORD_MERCADO", "pass")

    with patch("inpi.coleta_mercado.ClientePlataformaNova") as Cliente, \
         patch("inpi.coleta_mercado.proximo_lote", return_value=[]):
        mod.rodar_loop()

    Cliente.return_value.fechar.assert_called_once()
    assert "vazia" in capsys.readouterr().out.lower()


def test_rodar_loop_para_em_bloqueio_sem_dormir(monkeypatch):
    monkeypatch.setenv("INPI_PAG_LOGIN_MERCADO", "user")
    monkeypatch.setenv("INPI_PAG_PASSWORD_MERCADO", "pass")

    with patch("inpi.coleta_mercado.ClientePlataformaNova") as Cliente, \
         patch("inpi.coleta_mercado.proximo_lote", return_value=["P1"]), \
         patch("inpi.coleta_mercado.processar_lote",
               return_value={"erros": 1}), \
         patch("inpi.coleta_mercado.time.sleep") as mock_sleep:
        mod.rodar_loop(tamanho_lote=1, limiar_bloqueio=0.3)

    mock_sleep.assert_not_called()
    Cliente.return_value.fechar.assert_called_once()
