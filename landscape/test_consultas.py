"""Testes de landscape/consultas.py -- garante parametrizacao (sem concatenacao
de valor do usuario no SQL) e a ancora de fonte. Cliente BigQuery mockado."""

from __future__ import annotations

from unittest.mock import MagicMock

from google.cloud import bigquery

from landscape import consultas


def _cliente_mock() -> MagicMock:
    client = MagicMock()
    client.query.return_value.total_bytes_processed = 100
    client.query.return_value.result.return_value = []
    return client


def _sql_e_parametros(client: MagicMock) -> tuple[str, list]:
    # ultima chamada de client.query() e a execucao real (apos o dry-run)
    sql = client.query.call_args_list[-1].args[0]
    job_config = client.query.call_args_list[-1].kwargs["job_config"]
    return sql, job_config.query_parameters


def test_evolucao_temporal_parametriza_valor_do_usuario():
    client = _cliente_mock()
    consultas.evolucao_temporal(client, "H01L; DROP TABLE x", pais="BR")
    sql, params = _sql_e_parametros(client)
    assert "H01L; DROP TABLE x" not in sql
    assert "DROP TABLE" not in sql
    nomes = {p.name for p in params}
    assert "cpc_prefix" in nomes and "pais" in nomes


def test_top_titulares_parametriza_limite():
    client = _cliente_mock()
    consultas.top_titulares(client, "H01L", limite=5)
    sql, params = _sql_e_parametros(client)
    assert "5" not in sql  # limite vai por parametro, nao concatenado
    assert any(p.name == "limite" and p.value == 5 for p in params)


def test_co_classificacao_declara_fonte():
    client = _cliente_mock()
    resultado = consultas.co_classificacao(client, "H01L")
    assert resultado["fonte"] == consultas.FONTE


def test_perfil_titular_retorna_tecnologia_e_geografia():
    client = _cliente_mock()
    resultado = consultas.perfil_titular(client, "Acme Corp")
    assert "tecnologia" in resultado and "geografia" in resultado


def test_filtro_datas_converte_para_int_aaaammdd():
    parametros: list[bigquery.ScalarQueryParameter] = []
    clausula = consultas._filtro_datas("2020-01-15", "2021-12-31", parametros)
    assert "filing_date >= @desde" in clausula
    valores = {p.name: p.value for p in parametros}
    assert valores["desde"] == 20200115
    assert valores["ate"] == 20211231
