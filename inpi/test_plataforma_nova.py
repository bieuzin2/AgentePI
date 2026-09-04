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
