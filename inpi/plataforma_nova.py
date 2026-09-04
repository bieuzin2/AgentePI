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

    def get_bibliographic_data(self, numero_inpi: str) -> list[dict[str, Any]]:
        """Biblio + CPC/classificacao. numero_inpi: 12 digitos, sem 'BR', sem
        digito verificador (ex.: '102022010731'). Devolve a lista crua de
        campos INID (inid/whereDisplay/label/type/value) -- mapear pra dict
        por inid e responsabilidade de quem consome."""
        r = self._http.post(
            "/_classId/68b1dda7671584537112aca5/getBibliographicData",
            json={"processNumber": numero_inpi},
            headers=self._headers(),
        )
        if r.status_code != 200:
            raise PlataformaNovaError(
                f"getBibliographicData falhou pra {numero_inpi} "
                f"(status {r.status_code}): {r.text[:300]}")
        return r.json()

    def get_listing_data(self, numero_inpi: str, tipo: TipoListagem) -> dict[str, Any]:
        """Eventos de Pedido ou Anuidades. 'urlObjectId' -- NAO 'processNumber'
        nem 'urlObject' -- e o campo obrigatorio (ver docstring do modulo).
        customQuery vazio = sem filtro, traz o historico completo (a UI real
        aplica um filtro default que omite linhas ja pagas/indisponiveis;
        sem filtro fica mais proximo do que o pePI ja cobre hoje)."""
        component_id = (_COMPONENT_ID_EVENTOS if tipo == "eventos"
                        else _COMPONENT_ID_ANUIDADES)
        r = self._http.post(
            "/_classId/61bb893d05424e43e91eacd7/getListingData",
            json={
                "componentId": component_id,
                "customQuery": [],
                "customSort": None,
                "pageIndex": 0,
                "urlObjectId": numero_inpi,
            },
            headers=self._headers(),
        )
        if r.status_code != 200:
            raise PlataformaNovaError(
                f"getListingData({tipo}) falhou pra {numero_inpi} "
                f"(status {r.status_code}): {r.text[:300]}")
        return r.json()

    def fechar(self) -> None:
        self._http.close()
