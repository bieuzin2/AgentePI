"""Cliente HTTP para o Modulo de Servicos de Patentes do INPI
(servicos.patentes.inpi.gov.br), autenticado via login nativo PAG.

Confirmado ao vivo em 2026-09-04 (ver docs/pesquisa/inpi_plataforma_nova.md):
login devolve um JWT que funciona sozinho, sem cookie de sessao -- headless,
sem navegador, sem Tor. getListingData (eventos/anuidades) so responde 200
com o campo 'urlObjectId' -- NAO 'processNumber' nem 'urlObject', que sao os
nomes que a mensagem de erro do backend sugere e que NAO funcionam. So foi
possivel achar o nome certo capturando o request real da UI via DevTools.
"""

from __future__ import annotations

import time
from typing import Any, Literal

import httpx

BASE_URL = "https://servicos.patentes.inpi.gov.br/api/1/servicedesk-embedded"

# IDs fixos dos widgets 'lvt-listing-objects' da pagina /pag-pedido -- um por
# aba (Eventos de Pedido / Anuidades). Nao mudam por processo, so por deploy
# da SPA; se a plataforma nova redeploy a pagina com outro layout, revisitar.
_COMPONENT_ID_EVENTOS = "68b1f6ee6715845371898232"
_COMPONENT_ID_ANUIDADES = "68b5e7a93cf0f00ea5057fb3"

TipoListagem = Literal["eventos", "anuidades"]

# 502/503/504 = sobrecarga transitoria do gateway do INPI (observado ao vivo
# em paralelismo alto, 2026-09-04) -- diferente de 4xx (erro de cliente,
# definitivo) ou de bloqueio deliberado (que nao teria status de gateway
# genuino). Poucas tentativas com backoff curto: nao e evasao de bloqueio,
# e tolerancia a um servidor momentaneamente sobrecarregado.
_STATUS_RETRIAVEIS = {502, 503, 504}
_TENTATIVAS_GATEWAY = 3
_BACKOFF_BASE_SEGUNDOS = 1.0


class PlataformaNovaError(RuntimeError):
    """Erro de rede/autenticacao/resposta inesperada da API."""


class ClientePlataformaNova:
    """Sessao autenticada contra o Modulo de Servicos de Patentes.

    Um objeto = uma conta logada. Reautentica sozinho quando o token expira
    (checado pelo 'exp' do JWT, sem esperar 401). Sem cookies -- so
    Authorization: Bearer, testado standalone (credentials omit).
    """

    def __init__(self, login: str, senha: str, http: httpx.Client | None = None):
        self._login = login
        self._senha = senha
        self._http = http or httpx.Client(base_url=BASE_URL, timeout=30.0)
        self._token: str | None = None
        self._expira_em: float = 0.0

    def _autenticar(self) -> None:
        r = self._http.post(
            "/sys/auth/signIn/defaultAuthenticatorCustomer",
            json={"userLogin": self._login, "userPassword": self._senha},
        )
        if r.status_code != 200:
            raise PlataformaNovaError(
                f"login falhou (status {r.status_code}): {r.text[:300]}")
        corpo = r.json()
        if corpo.get("status") != "success":
            raise PlataformaNovaError(f"login recusado: {corpo}")
        self._token = corpo["accessToken"]["token"]
        self._expira_em = float(corpo["accessToken"]["payload"]["exp"])

    def _token_valido(self) -> bool:
        # 60s de folga pra nao expirar no meio de uma chamada em voo.
        return self._token is not None and time.time() < self._expira_em - 60

    def _headers(self) -> dict[str, str]:
        if not self._token_valido():
            self._autenticar()
        return {"Authorization": f"Bearer {self._token}"}

    def _post_com_retry(self, path: str, json_body: dict, contexto: str) -> Any:
        """POST com retry curto pra 502/503/504 (ver _STATUS_RETRIAVEIS) OU
        timeout de rede (httpx.TimeoutException -- ReadTimeout observado ao
        vivo em paralelismo alto: servidor sobrecarregado, nao responde
        dentro do prazo, sem sequer devolver status). Mesma classe de
        sobrecarga transitoria, mesmo backoff curto -- nao e retry contra
        bloqueio deliberado (nunca vimos 403/429 aqui).

        Qualquer outro status (4xx, ou 5xx fora da lista) levanta na
        primeira tentativa -- retry ali so atrasaria o fallback pro pePI."""
        ultimo_status: int | None = None
        ultimo_corpo = ""
        ultimo_timeout: httpx.TimeoutException | None = None
        for tentativa in range(1, _TENTATIVAS_GATEWAY + 1):
            try:
                r = self._http.post(path, json=json_body, headers=self._headers())
            except httpx.TimeoutException as exc:
                ultimo_timeout = exc
                if tentativa == _TENTATIVAS_GATEWAY:
                    break
                time.sleep(_BACKOFF_BASE_SEGUNDOS * tentativa)
                continue
            ultimo_timeout = None
            if r.status_code == 200:
                return r.json()
            ultimo_status, ultimo_corpo = r.status_code, r.text[:300]
            if r.status_code not in _STATUS_RETRIAVEIS or tentativa == _TENTATIVAS_GATEWAY:
                break
            time.sleep(_BACKOFF_BASE_SEGUNDOS * tentativa)
        if ultimo_timeout is not None:
            raise PlataformaNovaError(
                f"{contexto} ({type(ultimo_timeout).__name__}): {ultimo_timeout}")
        raise PlataformaNovaError(f"{contexto} (status {ultimo_status}): {ultimo_corpo}")

    def get_bibliographic_data(self, numero_inpi: str) -> list[dict[str, Any]]:
        """Biblio + CPC/classificacao. numero_inpi: 12 digitos, sem 'BR', sem
        digito verificador (ex.: '102022010731'). Devolve a lista crua de
        campos INID (inid/whereDisplay/label/type/value) -- mapear pra dict
        por inid e responsabilidade de quem consome."""
        return self._post_com_retry(
            "/_classId/68b1dda7671584537112aca5/getBibliographicData",
            {"processNumber": numero_inpi},
            f"getBibliographicData falhou pra {numero_inpi}",
        )

    def get_listing_data(self, numero_inpi: str, tipo: TipoListagem) -> dict[str, Any]:
        """Eventos de Pedido ou Anuidades. 'urlObjectId' -- NAO 'processNumber'
        nem 'urlObject' -- e o campo obrigatorio (ver docstring do modulo).
        customQuery vazio = sem filtro, traz o historico completo (a UI real
        aplica um filtro default que omite linhas ja pagas/indisponiveis;
        sem filtro fica mais proximo do que o pePI ja cobre hoje)."""
        component_id = (_COMPONENT_ID_EVENTOS if tipo == "eventos"
                        else _COMPONENT_ID_ANUIDADES)
        return self._post_com_retry(
            "/_classId/61bb893d05424e43e91eacd7/getListingData",
            {
                "componentId": component_id,
                "customQuery": [],
                "customSort": None,
                "pageIndex": 0,
                "urlObjectId": numero_inpi,
            },
            f"getListingData({tipo}) falhou pra {numero_inpi}",
        )

    def fechar(self) -> None:
        self._http.close()
