"""Testes do lens_mcp que rodam SEM token e SEM rede."""

import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(__file__))
import lens_mcp as m


def test_titulo_prefere_ingles():
    # invention_title vem como lista de {text, lang}; o registro coreano real
    # traz o titulo em ko e en.
    item = {
        "biblio": {
            "invention_title": [
                {"text": "생분해성 포장 패키지", "lang": "ko"},
                {"text": "Biodegradable packaging package", "lang": "en"},
            ]
        }
    }
    assert m._titulo(item) == "Biodegradable packaging package"


def test_titulo_cai_no_primeiro_quando_nao_ha_ingles():
    item = {"biblio": {"invention_title": [{"text": "Embalagem", "lang": "pt"}]}}
    assert m._titulo(item) == "Embalagem"


def test_titulo_aceita_dict_unico_e_string():
    assert m._titulo({"biblio": {"invention_title": {"text": "X", "lang": "pt"}}}) == "X"
    assert m._titulo({"title": "Y"}) == "Y"
    assert m._titulo({}) == ""


def test_txt_desempacota_value_e_text():
    assert m._txt({"value": "FMS KOREA CO LTD"}) == "FMS KOREA CO LTD"
    assert m._txt({"text": "abc"}) == "abc"
    assert m._txt(None) == ""


def test_carimbo_de_licenca_existe():
    """Enquanto o trial durar, toda saida tem que sair marcada -- os termos do
    Lens vedam uso comercial do output. Apagar o carimbo e uma decisao, nao um
    acidente: este teste faz a decisao aparecer."""
    assert "avaliacao" in m.CARIMBO.lower()


def test_token_ausente_falha_alto(monkeypatch):
    monkeypatch.delenv("LENS_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="LENS_TOKEN"):
        m._token()


def test_401_explica_que_os_produtos_sao_separados(monkeypatch):
    """Regressao do achado do aceite: o token de trial cobria Patent API mas nao
    Scholarly. Um 401 cru mandaria o operador conferir a chave -- que esta certa."""
    monkeypatch.setenv("LENS_TOKEN", "fake")

    def falso_post(url, headers=None, json=None, timeout=None):
        return httpx.Response(401, request=httpx.Request("POST", url))

    monkeypatch.setattr(m.httpx, "post", falso_post)
    with pytest.raises(PermissionError, match="assinaturas separadas"):
        m._post("/scholarly/search", {})


def test_429_e_reportado_como_limite(monkeypatch):
    monkeypatch.setenv("LENS_TOKEN", "fake")
    monkeypatch.setattr(
        m.httpx, "post",
        lambda url, **k: httpx.Response(429, request=httpx.Request("POST", url)),
    )
    with pytest.raises(RuntimeError, match="429"):
        m._post("/patent/search", {})
