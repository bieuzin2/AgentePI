from __future__ import annotations

import json
import time

import httpx
import pytest

from inpi.plataforma_nova import (
    ClientePlataformaNova,
    PlataformaNovaError,
    _COMPONENT_ID_ANUIDADES,
    _COMPONENT_ID_EVENTOS,
)


def _cliente_mock(handler) -> ClientePlataformaNova:
    transporte = httpx.MockTransport(handler)
    http = httpx.Client(
        base_url="https://servicos.patentes.inpi.gov.br/api/1/servicedesk-embedded",
        transport=transporte,
    )
    return ClientePlataformaNova("usuario", "senha", http=http)


def _resposta_login(exp: float) -> dict:
    return {
        "code": "abc", "name": "Fulano", "login": "usuario",
        "accessToken": {"token": "jwt-fake", "payload": {"exp": exp}},
        "endpoint": "/", "status": "success",
    }


def test_login_autentica_uma_vez_e_reusa_token():
    chamadas = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(request.url.path)
        if request.url.path.endswith("/signIn/defaultAuthenticatorCustomer"):
            return httpx.Response(200, json=_resposta_login(time.time() + 3600))
        return httpx.Response(200, json=[])

    cliente = _cliente_mock(handler)
    cliente.get_bibliographic_data("102022010731")
    cliente.get_bibliographic_data("102022010731")

    assert sum(1 for c in chamadas if c.endswith("/sys/auth/signIn/defaultAuthenticatorCustomer")) == 1


def test_reautentica_quando_token_expirado():
    logins = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/signIn/defaultAuthenticatorCustomer"):
            logins.append(1)
            return httpx.Response(200, json=_resposta_login(time.time() - 1))
        return httpx.Response(200, json=[])

    cliente = _cliente_mock(handler)
    cliente.get_bibliographic_data("102022010731")
    cliente.get_bibliographic_data("102022010731")

    assert len(logins) == 2


def test_login_com_status_diferente_de_success_levanta_erro():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "fail", "message": "senha errada"})

    cliente = _cliente_mock(handler)
    with pytest.raises(PlataformaNovaError):
        cliente.get_bibliographic_data("102022010731")


def test_get_bibliographic_data_envia_processo_sem_prefixo():
    corpos = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/signIn/defaultAuthenticatorCustomer"):
            return httpx.Response(200, json=_resposta_login(time.time() + 3600))
        corpos.append(json.loads(request.content))
        return httpx.Response(200, json=[{"inid": "54", "value": "TITULO"}])

    cliente = _cliente_mock(handler)
    resultado = cliente.get_bibliographic_data("102022010731")

    assert corpos == [{"processNumber": "102022010731"}]
    assert resultado == [{"inid": "54", "value": "TITULO"}]


def test_get_listing_data_usa_url_object_id_e_component_id_certo():
    corpos = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/signIn/defaultAuthenticatorCustomer"):
            return httpx.Response(200, json=_resposta_login(time.time() + 3600))
        corpos.append(json.loads(request.content))
        return httpx.Response(200, json={"total": 0, "objects": []})

    cliente = _cliente_mock(handler)
    cliente.get_listing_data("102022010731", "anuidades")
    cliente.get_listing_data("102022010731", "eventos")

    assert corpos[0]["urlObjectId"] == "102022010731"
    assert corpos[0]["componentId"] == _COMPONENT_ID_ANUIDADES
    assert "processNumber" not in corpos[0]
    assert corpos[1]["componentId"] == _COMPONENT_ID_EVENTOS


def test_status_diferente_de_200_levanta_erro_com_corpo():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/signIn/defaultAuthenticatorCustomer"):
            return httpx.Response(200, json=_resposta_login(time.time() + 3600))
        return httpx.Response(400, json={"generalMessages": [{"text": "erro"}]})

    cliente = _cliente_mock(handler)
    with pytest.raises(PlataformaNovaError, match="400"):
        cliente.get_bibliographic_data("000000000000")


def test_504_gateway_timeout_faz_retry_e_recupera(monkeypatch):
    """504 e sobrecarga transitoria do gateway do INPI (observado ao vivo em
    paralelismo alto), nao bloqueio deliberado -- poucas tentativas com
    backoff curto, depois volta a funcionar (nao insiste pra sempre)."""
    monkeypatch.setattr("inpi.plataforma_nova.time.sleep", lambda s: None)
    tentativas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/signIn/defaultAuthenticatorCustomer"):
            return httpx.Response(200, json=_resposta_login(time.time() + 3600))
        tentativas["n"] += 1
        if tentativas["n"] < 3:
            return httpx.Response(504, text="Gateway Time-out")
        return httpx.Response(200, json=[{"inid": "52", "value": "A61K"}])

    cliente = _cliente_mock(handler)
    resultado = cliente.get_bibliographic_data("102022010731")

    assert resultado == [{"inid": "52", "value": "A61K"}]
    assert tentativas["n"] == 3


def test_504_gateway_timeout_persistente_ainda_levanta_erro_apos_tentativas(monkeypatch):
    monkeypatch.setattr("inpi.plataforma_nova.time.sleep", lambda s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/signIn/defaultAuthenticatorCustomer"):
            return httpx.Response(200, json=_resposta_login(time.time() + 3600))
        return httpx.Response(504, text="Gateway Time-out")

    cliente = _cliente_mock(handler)
    with pytest.raises(PlataformaNovaError, match="504"):
        cliente.get_bibliographic_data("102022010731")


def test_400_nao_faz_retry_levanta_na_primeira_tentativa(monkeypatch):
    """So 502/503/504 (sobrecarga de gateway) tem retry -- erro de cliente
    (400, processo nao encontrado etc.) e definitivo, retry so atrasaria o
    fallback pro pePI a toa."""
    chamadas = {"n": 0}
    monkeypatch.setattr("inpi.plataforma_nova.time.sleep", lambda s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/signIn/defaultAuthenticatorCustomer"):
            return httpx.Response(200, json=_resposta_login(time.time() + 3600))
        chamadas["n"] += 1
        return httpx.Response(400, json={"text": "erro"})

    cliente = _cliente_mock(handler)
    with pytest.raises(PlataformaNovaError, match="400"):
        cliente.get_bibliographic_data("102022010731")
    assert chamadas["n"] == 1


def test_read_timeout_faz_retry_e_recupera(monkeypatch):
    """ReadTimeout (servidor nao respondeu dentro do prazo, sem status HTTP
    algum) e a mesma classe de sobrecarga transitoria que 502/503/504 --
    tambem merece retry curto, nao so status explicito."""
    monkeypatch.setattr("inpi.plataforma_nova.time.sleep", lambda s: None)
    tentativas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/signIn/defaultAuthenticatorCustomer"):
            return httpx.Response(200, json=_resposta_login(time.time() + 3600))
        tentativas["n"] += 1
        if tentativas["n"] < 3:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json=[{"inid": "52", "value": "A61K"}])

    cliente = _cliente_mock(handler)
    resultado = cliente.get_bibliographic_data("102022010731")

    assert resultado == [{"inid": "52", "value": "A61K"}]
    assert tentativas["n"] == 3


def test_read_timeout_persistente_ainda_levanta_erro_apos_tentativas(monkeypatch):
    monkeypatch.setattr("inpi.plataforma_nova.time.sleep", lambda s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/signIn/defaultAuthenticatorCustomer"):
            return httpx.Response(200, json=_resposta_login(time.time() + 3600))
        raise httpx.ReadTimeout("timed out", request=request)

    cliente = _cliente_mock(handler)
    with pytest.raises(PlataformaNovaError, match="ReadTimeout|timed out"):
        cliente.get_bibliographic_data("102022010731")
