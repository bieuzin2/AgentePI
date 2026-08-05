"""Testes de landscape/bigquery_client.py -- tudo mockado, nunca bate em rede real."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from landscape.bigquery_client import ConsultaMuitoGrandeError, estimar_bytes, executar


def _cliente_mock(bytes_estimados: int, linhas: list | None = None) -> MagicMock:
    client = MagicMock()
    client.query.return_value.total_bytes_processed = bytes_estimados
    client.query.return_value.result.return_value = linhas or []
    return client


def test_estimar_bytes_faz_dry_run():
    client = _cliente_mock(12345)
    assert estimar_bytes(client, "SELECT 1") == 12345
    _, kwargs = client.query.call_args
    assert kwargs["job_config"].dry_run is True


def test_executar_recusa_acima_de_10gb_sem_confirmacao():
    client = _cliente_mock(11 * 1024 ** 3)
    with pytest.raises(ConsultaMuitoGrandeError):
        executar(client, "SELECT 1")


def test_executar_aceita_acima_de_10gb_com_confirmacao():
    client = _cliente_mock(11 * 1024 ** 3, linhas=[])
    resultado = executar(client, "SELECT 1", confirmar_acima_10gb=True)
    assert resultado == []


def test_executar_roda_normal_abaixo_do_teto():
    linha = MagicMock()
    linha.items.return_value = [("titular", "Acme")]
    client = _cliente_mock(1024, linhas=[linha])
    resultado = executar(client, "SELECT 1")
    assert resultado == [{"titular": "Acme"}]


def test_teto_customizado():
    client = _cliente_mock(5 * 1024 ** 3)
    with pytest.raises(ConsultaMuitoGrandeError):
        executar(client, "SELECT 1", teto_bytes=1024)
