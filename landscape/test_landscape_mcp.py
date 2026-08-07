"""Testes do servidor MCP landscape -- cliente BigQuery e cache mockados,
sem tocar em rede ou banco real."""

from __future__ import annotations

from unittest.mock import patch

from landscape import landscape_mcp, mcp_app


def test_evolucao_temporal_usa_cache_quando_disponivel():
    with patch.object(mcp_app.cache, "obter", return_value={"linhas": [1]}) as obter, \
         patch.object(mcp_app, "cliente") as cliente_mock:
        resultado = landscape_mcp.landscape_evolucao_temporal("H01L")
        assert resultado["cache"] is True
        cliente_mock.assert_not_called()
    obter.assert_called_once()


def test_top_titulares_bate_no_bigquery_e_salva_cache_quando_vazio():
    with patch.object(mcp_app.cache, "obter", return_value=None), \
         patch.object(mcp_app.cache, "salvar") as salvar, \
         patch.object(mcp_app, "cliente"), \
         patch.object(landscape_mcp.consultas, "top_titulares",
                       return_value={"fonte": "x", "linhas": []}) as consulta:
        resultado = landscape_mcp.landscape_top_titulares("H01L", limite=5)
        assert resultado["cache"] is False
        consulta.assert_called_once()
        salvar.assert_called_once()


def test_erro_de_credencial_e_claro_sem_adc():
    from landscape.bigquery_client import cliente as cliente_real
    with patch("landscape.bigquery_client.bigquery.Client", side_effect=Exception("sem ADC")):
        try:
            cliente_real()
            raise AssertionError("deveria ter levantado RuntimeError")
        except RuntimeError as exc:
            assert "gcloud auth application-default login" in str(exc)
