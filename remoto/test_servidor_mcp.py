"""Testes de remoto/servidor_mcp.py -- middleware de chave de API, sem rede
nem chamar nenhuma tool de verdade (essas ja tem teste nos modulos de origem)."""

import os

import pytest

os.environ.setdefault("API_KEY_AGENTE_PI", "teste-fixo-para-import")

from remoto.servidor_mcp import TOOLS, _chave_valida, montar_app  # noqa: E402


def test_chave_por_authorization_bearer():
    assert _chave_valida({"authorization": "Bearer abc"}, "abc") is True


def test_chave_por_x_api_key():
    assert _chave_valida({"x-api-key": "abc"}, "abc") is True


def test_chave_ausente_recusa():
    assert _chave_valida({}, "abc") is False


def test_chave_errada_recusa():
    assert _chave_valida({"authorization": "Bearer xyz"}, "abc") is False


def test_esperada_vazia_nunca_valida(monkeypatch):
    # Defensivo: mesmo que a chave configurada esteja vazia por engano, nunca
    # aceita "qualquer coisa == vazio".
    assert _chave_valida({"authorization": "Bearer "}, "") is False


def test_todas_as_tools_curadas_sao_callables():
    assert len(TOOLS) > 0
    for fn in TOOLS:
        assert callable(fn)


def test_montar_app_recusa_sem_chave_configurada(monkeypatch):
    monkeypatch.delenv("API_KEY_AGENTE_PI", raising=False)
    with pytest.raises(RuntimeError, match="API_KEY_AGENTE_PI"):
        montar_app()


def test_health_nao_exige_chave():
    from starlette.testclient import TestClient

    app = montar_app()
    cliente = TestClient(app)
    resposta = cliente.get("/health")
    assert resposta.status_code == 200
    assert resposta.json()["tools"] == len(TOOLS)


def test_tools_lista_nomes_sem_exigir_chave():
    from starlette.testclient import TestClient

    app = montar_app()
    cliente = TestClient(app)
    resposta = cliente.get("/tools")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total"] == len(TOOLS)
    # as tools novas do ledger do pePI precisam estar expostas
    assert "inpi_anuidades_pagas" in corpo["tools"]
    assert "inpi_peticoes_escritorio" in corpo["tools"]


def test_mcp_recusa_sem_chave():
    from starlette.testclient import TestClient

    app = montar_app()
    cliente = TestClient(app)
    resposta = cliente.post("/mcp", json={})
    assert resposta.status_code == 401


def test_mcp_recusa_chave_errada():
    from starlette.testclient import TestClient

    app = montar_app()
    cliente = TestClient(app)
    resposta = cliente.post("/mcp", json={}, headers={"Authorization": "Bearer errada"})
    assert resposta.status_code == 401
