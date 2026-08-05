from __future__ import annotations

import httpx
import pytest

from busca import openalex


class _RespostaFake:
    def __init__(self, corpo):
        self._corpo = corpo

    def raise_for_status(self):
        pass

    def json(self):
        return self._corpo


def test_buscar_extrai_campos(monkeypatch, tmp_path):
    monkeypatch.setattr(openalex, "CACHE", tmp_path)
    corpo = {
        "meta": {"count": 1},
        "results": [{
            "title": "Embalagem biodegradavel",
            "doi": "10.1/x",
            "publication_year": 2020,
            "publication_date": "2020-05-01",
            "authorships": [{"author": {"display_name": "Fulano"}}],
            "cited_by_count": 3,
            "id": "https://openalex.org/W1",
        }],
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _RespostaFake(corpo))

    d = openalex.buscar("biodegradable packaging")
    assert d["retornados"] == 1
    r = d["resultados"][0]
    assert r["titulo"] == "Embalagem biodegradavel"
    assert r["autores"] == ["Fulano"]
    assert r["fonte"] == "openalex"


def test_buscar_sem_termo_erro():
    assert openalex.buscar("  ").get("erro") is True


def test_buscar_usa_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(openalex, "CACHE", tmp_path)
    chamadas = {"n": 0}

    def fake_get(*a, **k):
        chamadas["n"] += 1
        return _RespostaFake({"meta": {"count": 0}, "results": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    openalex.buscar("teste")
    openalex.buscar("teste")
    assert chamadas["n"] == 1


def test_buscar_erro_http_nao_derruba(monkeypatch, tmp_path):
    monkeypatch.setattr(openalex, "CACHE", tmp_path)

    def fake_get(*a, **k):
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx, "get", fake_get)
    d = openalex.buscar("teste")
    assert d["erro"] is True
    assert d["resultados"] == []
