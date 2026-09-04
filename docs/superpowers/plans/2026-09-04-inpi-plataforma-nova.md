# Plataforma Nova INPI — Substituir pePI + Ingestão Estatística Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir o cliente headless do Módulo de Serviços de Patentes do INPI (login PAG + biblio + anuidades/eventos), o script de validação de volume que decide se o pePI+Tor pode ser desligado, e a ingestão do Portal de Estatísticas público (dado agregado nacional) numa nova tool MCP.

**Architecture:** Stream A (cliente HTTP `inpi/plataforma_nova.py` → orquestrador `inpi/coleta_plataforma_nova.py` que reusa `registrar()` de `inpi/coleta_ficha_extras.py`, escrevendo no MESMO `ficha-extras.csv` → script de validação `inpi/validar_plataforma_nova.py`). Stream B (`inpi/estatistica_publica.py` baixa via Chromium headless → CSV → `inpi/ingest.py` carrega tabela `estatistica_nacional` → tool `inpi_estatistica_nacional`). As duas streams são independentes entre si; a ordem das tasks segue A depois B mas B não depende de A.

**Tech Stack:** Python 3.12, httpx (cliente HTTP, já dependência), duckdb (já dependência), Playwright (NOVA dependência, só Stream B), pytest com `httpx.MockTransport` (sem lib de mock extra).

## Global Constraints

- Nenhuma mudança de schema em `ficha_extras`/`ficha_peticoes`/`ficha_anuidades` — o novo coletor reusa `registrar()` e o CSV existente (`inpi/referencias/ficha-extras.csv`), formato `numero_inpi,cpc,peticoes_json,anuidades_json,link_documento,escritorio_canonico,fonte,coletado_em`.
- `numero_inpi`/`urlObjectId` na plataforma nova: 12 dígitos, sem `BR`, sem espaço, sem dígito verificador (ex. `102022010731`) — confirmado ao vivo, ver `docs/pesquisa/inpi_plataforma_nova.md`.
- Testes que fazem rede real (login de verdade, Playwright de verdade) usam `@pytest.mark.online` (marker já existe em `pyproject.toml`, excluído por padrão via `addopts = -m "not online"`) — nunca rodam no fluxo padrão de CI/local.
- Credenciais da conta PAG dedicada vêm de `INPI_PAG_LOGIN`/`INPI_PAG_PASSWORD` no `.env` (mesmo padrão de carregamento de `MOTHERDUCK_TOKEN` via `python-dotenv`) — nunca hardcoded, nunca en teste.
- `con()` (`inpi/db.py`) é read-only — nenhuma task escreve no `.duckdb` diretamente; tudo passa por CSV + `inpi/ingest.py`, igual ao padrão existente.
- `inpi/coleta_ficha_extras.py`, `inpi/coleta_sigilo.py`, `inpi/tor_proxy.py` NÃO são tocados nem removidos por este plano — seguem intactos como fallback.

---

### Task 1: Cliente HTTP da plataforma nova (login + biblio + listing)

**Files:**
- Create: `inpi/plataforma_nova.py`
- Test: `inpi/test_plataforma_nova.py`

**Interfaces:**
- Produces: `class ClientePlataformaNova(login: str, senha: str, http: httpx.Client | None = None)` com métodos `get_bibliographic_data(numero_inpi: str) -> list[dict]` e `get_listing_data(numero_inpi: str, tipo: Literal["eventos", "anuidades"]) -> dict` (devolve `{"total": int, "objects": [{"value": list, ...}], ...}`); `class PlataformaNovaError(RuntimeError)`.

- [ ] **Step 1: Escrever os testes (falhando)**

```python
# inpi/test_plataforma_nova.py
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

    assert chamadas.count("/sys/auth/signIn/defaultAuthenticatorCustomer") == 1


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
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `python -m pytest inpi/test_plataforma_nova.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'inpi.plataforma_nova'`

- [ ] **Step 3: Implementar o cliente**

```python
# inpi/plataforma_nova.py
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
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `python -m pytest inpi/test_plataforma_nova.py -v`
Expected: PASS (6 testes)

- [ ] **Step 5: Commit**

```bash
git add inpi/plataforma_nova.py inpi/test_plataforma_nova.py
git commit -m "feat(inpi): cliente headless da plataforma nova (login PAG + biblio + listing)"
```

---

### Task 2: Orquestrador — coletar via plataforma nova e gravar no ficha-extras.csv existente

**Files:**
- Create: `inpi/coleta_plataforma_nova.py`
- Test: `inpi/test_coleta_plataforma_nova.py`

**Interfaces:**
- Consumes: `ClientePlataformaNova` (Task 1) — `get_bibliographic_data`, `get_listing_data`, `PlataformaNovaError`; `registrar(numero_inpi, campos, escritorio_canonico, fonte, coletado_em, link_documento="") -> bool` de `inpi.coleta_ficha_extras`.
- Produces: `coletar_e_registrar(cliente, numeros_inpi: list[str], escritorio_canonico: str, fonte: str = "Módulo de Serviços de Patentes INPI (headless)") -> dict` (resumo `{"registrados", "sem_biblio", "ja_coletado_ou_invalido", "erros"}`).

- [ ] **Step 1: Escrever os testes (falhando)**

```python
# inpi/test_coleta_plataforma_nova.py
from __future__ import annotations

from unittest.mock import MagicMock

from inpi.coleta_plataforma_nova import (
    _extrair_cpc,
    _mapear_anuidade,
    coletar_e_registrar,
)
from inpi.plataforma_nova import PlataformaNovaError


def test_mapear_anuidade_extrai_numero_gru_valor_data_e_situacao():
    # Forma real observada em getListingData (2026-09-04), coluna 'value':
    # [Anuidade, GRU, prazo ordinario, prazo extraordinario, valor, data pagamento, situacao HTML]
    value = [
        "5ª Anuidade", "1234567", "01/06/2026<br>01/09/2026",
        "02/09/2026<br>01/03/2027", "R$ 435,00", "10/05/2026",
        '<div><span style="white-space: nowrap;">Averbada</span></div>',
    ]
    item = _mapear_anuidade(value)
    assert item == {
        "numero": "5", "status": "Averbada", "gru": "1234567",
        "valor": "R$ 435,00", "data_pagamento": "10/05/2026",
    }


def test_mapear_anuidade_com_campos_vazios_nao_quebra():
    value = ["7ª Anuidade", "", "01/06/2028<br>01/09/2028",
             "02/09/2028<br>01/03/2029", "", "",
             '<div><span>Indisponível</span></div>']
    item = _mapear_anuidade(value)
    assert item["numero"] == "7"
    assert item["gru"] is None
    assert item["valor"] is None
    assert item["status"] == "Indisponível"


def test_extrair_cpc_pega_campo_inid_52():
    biblio = [
        {"inid": "51", "value": "C08L 5/04"},
        {"inid": "52", "value": "C08L 5/04; C08L 99/00"},
    ]
    assert _extrair_cpc(biblio) == "C08L 5/04; C08L 99/00"


def test_extrair_cpc_ausente_devolve_none():
    assert _extrair_cpc([{"inid": "51", "value": "C08L 5/04"}]) is None


def test_coletar_e_registrar_chama_registrar_com_campos_mapeados(monkeypatch):
    cliente = MagicMock()
    cliente.get_bibliographic_data.return_value = [
        {"inid": "52", "value": "C08L 5/04"},
    ]
    cliente.get_listing_data.return_value = {
        "objects": [{"value": ["5ª Anuidade", "123", "", "", "R$ 100,00",
                               "01/01/2026", '<span>Averbada</span>']}],
    }

    chamadas = []
    monkeypatch.setattr(
        "inpi.coleta_plataforma_nova.registrar",
        lambda *a, **kw: chamadas.append((a, kw)) or True,
    )

    resumo = coletar_e_registrar(cliente, ["102022010731"], "clarke")

    assert resumo == {"registrados": 1, "sem_biblio": 0,
                      "ja_coletado_ou_invalido": 0, "erros": 0}
    (numero, campos, escritorio, fonte, coletado_em), kwargs = chamadas[0]
    assert numero == "102022010731"
    assert campos["cpc"] == "C08L 5/04"
    assert campos["anuidades"] == [
        {"numero": "5", "status": "Averbada", "gru": "123",
         "valor": "R$ 100,00", "data_pagamento": "01/01/2026"},
    ]
    assert campos["peticoes"] == []
    assert escritorio == "clarke"
    assert fonte == "Módulo de Serviços de Patentes INPI (headless)"


def test_coletar_e_registrar_conta_erro_sem_derrubar_o_lote(monkeypatch):
    cliente = MagicMock()
    cliente.get_bibliographic_data.side_effect = PlataformaNovaError("500")
    monkeypatch.setattr("inpi.coleta_plataforma_nova.registrar", lambda *a, **kw: True)

    resumo = coletar_e_registrar(cliente, ["102022010731", "102022010732"], "clarke")

    assert resumo == {"registrados": 0, "sem_biblio": 0,
                      "ja_coletado_ou_invalido": 0, "erros": 2}


def test_coletar_e_registrar_sem_biblio_nao_chama_listing(monkeypatch):
    cliente = MagicMock()
    cliente.get_bibliographic_data.return_value = []
    monkeypatch.setattr("inpi.coleta_plataforma_nova.registrar", lambda *a, **kw: True)

    resumo = coletar_e_registrar(cliente, ["102022010731"], "clarke")

    assert resumo["sem_biblio"] == 1
    cliente.get_listing_data.assert_not_called()
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `python -m pytest inpi/test_coleta_plataforma_nova.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'inpi.coleta_plataforma_nova'`

- [ ] **Step 3: Implementar o orquestrador**

```python
# inpi/coleta_plataforma_nova.py
"""Coleta via o Modulo de Servicos de Patentes (plataforma nova, headless,
ver inpi/plataforma_nova.py) e grava no MESMO ficha-extras.csv que
inpi/coleta_ficha_extras.py usa -- reusa registrar() sem tocar no schema
(ficha_extras/ficha_peticoes/ficha_anuidades continuam vindo do mesmo CSV
via inpi/ingest.py).

'peticoes' sai sempre vazio aqui: 'Eventos de Pedido' (a outra aba da
plataforma nova) NAO foi confirmado como equivalente a 'Peticoes/Servicos'
do pePI (podem ser conceitos diferentes -- despacho processual vs peticao
protocolada com GRU). Ate confirmar isso na validacao de volume (ver
inpi/validar_plataforma_nova.py), so anuidades e coletado daqui; peticoes
continua vindo so do pePI.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from inpi.coleta_ficha_extras import registrar
from inpi.plataforma_nova import ClientePlataformaNova, PlataformaNovaError

FONTE_PADRAO = "Módulo de Serviços de Patentes INPI (headless)"


def _mapear_anuidade(value: list) -> dict[str, Any]:
    """Traduz uma linha de getListingData(tipo='anuidades') (array posicional
    'value', ordem confirmada ao vivo: Anuidade, GRU, prazo ordinario, prazo
    extraordinario, valor pago, data de pagamento, situacao da averbacao em
    HTML) pro mesmo shape que o parser do pePI ja produz (numero/status/gru/
    valor/data_pagamento) -- so assim ficha_anuidades continua com um schema
    so, nao importa a fonte."""
    campos = list(value) + [None] * (7 - len(value))
    rotulo, gru, _prazo_ord, _prazo_extra, valor, data_pagamento, situacao_html = campos[:7]
    m = re.search(r"\d+", rotulo or "")
    situacao = BeautifulSoup(situacao_html or "", "html.parser").get_text(strip=True)
    return {
        "numero": m.group(0) if m else None,
        "status": situacao or None,
        "gru": gru or None,
        "valor": valor or None,
        "data_pagamento": data_pagamento or None,
    }


def _extrair_cpc(biblio: list[dict[str, Any]]) -> str | None:
    """Campo INID 52 ('Classificacao Nacional') -- mesmo campo que o parser
    do pePI le como CPC (ver campo_por_codigo(soup, '(52)') em
    coleta_ficha_extras.py)."""
    for campo in biblio:
        if campo.get("inid") == "52":
            return campo.get("value") or None
    return None


def coletar_e_registrar(
    cliente: ClientePlataformaNova, numeros_inpi: list[str],
    escritorio_canonico: str, fonte: str = FONTE_PADRAO,
) -> dict[str, int]:
    """Para cada numero_inpi: busca biblio (pra CPC) + anuidades, mapeia pro
    shape do registrar() existente, grava. Erro de rede/API num processo NAO
    derruba o lote inteiro -- so conta em 'erros' e segue pro proximo."""
    resumo = {"registrados": 0, "sem_biblio": 0, "ja_coletado_ou_invalido": 0, "erros": 0}
    for numero_inpi in numeros_inpi:
        try:
            biblio = cliente.get_bibliographic_data(numero_inpi)
            if not biblio:
                resumo["sem_biblio"] += 1
                continue
            listagem = cliente.get_listing_data(numero_inpi, "anuidades")
            anuidades = [_mapear_anuidade(obj["value"])
                        for obj in listagem.get("objects", [])]
            campos = {"cpc": _extrair_cpc(biblio), "peticoes": [], "anuidades": anuidades}
            ok = registrar(numero_inpi, campos, escritorio_canonico, fonte,
                           date.today().isoformat())
            resumo["registrados" if ok else "ja_coletado_ou_invalido"] += 1
        except PlataformaNovaError:
            resumo["erros"] += 1
    return resumo
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `python -m pytest inpi/test_coleta_plataforma_nova.py -v`
Expected: PASS (6 testes)

- [ ] **Step 5: Commit**

```bash
git add inpi/coleta_plataforma_nova.py inpi/test_coleta_plataforma_nova.py
git commit -m "feat(inpi): orquestrador da plataforma nova reusa registrar() do ficha-extras"
```

---

### Task 3: Script de validação de volume (decide se dá pra desligar o pePI+Tor)

**Files:**
- Create: `inpi/validar_plataforma_nova.py`
- Test: `inpi/test_validar_plataforma_nova.py`

**Interfaces:**
- Consumes: `ClientePlataformaNova`, `PlataformaNovaError` (Task 1); `_linhas(sql, params) -> list[dict]` de `inpi.consulta`.
- Produces: `amostrar_processos(escritorio_canonico: str | None, tamanho: int, dias_recentes: int) -> list[dict]`; `montar_relatorio(resultados: list[dict]) -> dict`; `rodar_validacao(cliente, escritorio_canonico=None, tamanho=1000, dias_recentes=45) -> dict` (rede real, não chamado em teste).

- [ ] **Step 1: Escrever os testes (falhando)**

```python
# inpi/test_validar_plataforma_nova.py
from __future__ import annotations

import duckdb

import inpi.consulta as consulta
from inpi.validar_plataforma_nova import amostrar_processos, montar_relatorio


def test_montar_relatorio_separa_recentes_de_antigos_e_calcula_taxas():
    resultados = [
        {"numero_inpi": "1", "recente": True, "sucesso": True, "indexado": True, "erro": None},
        {"numero_inpi": "2", "recente": True, "sucesso": False, "indexado": None, "erro": "500"},
        {"numero_inpi": "3", "recente": False, "sucesso": True, "indexado": True, "erro": None},
    ]
    r = montar_relatorio(resultados)

    assert r["total_amostrado"] == 3
    assert r["recentes"] == {"total": 2, "sucesso": 1, "indexado": 1,
                             "taxa_sucesso": 0.5, "taxa_indexado": 0.5}
    assert r["antigos"] == {"total": 1, "sucesso": 1, "indexado": 1,
                            "taxa_sucesso": 1.0, "taxa_indexado": 1.0}
    assert r["erros_exemplo"] == ["500"]


def test_montar_relatorio_com_grupo_vazio_nao_quebra():
    r = montar_relatorio([])
    assert r["recentes"]["total"] == 0
    assert r["recentes"]["taxa_sucesso"] is None


def test_amostrar_processos_separa_recentes_e_antigos(monkeypatch, tmp_path):
    banco = duckdb.connect(str(tmp_path / "fixture.duckdb"))
    banco.execute("""
      CREATE TABLE biblio (numero_inpi VARCHAR, data_deposito DATE)
    """)
    banco.execute("""
      CREATE TABLE ficha_extras (numero_inpi VARCHAR, cpc VARCHAR,
        escritorio_canonico VARCHAR, fonte VARCHAR, coletado_em VARCHAR)
    """)
    banco.execute("INSERT INTO biblio VALUES "
                  "('1', DATE '2026-08-20'), ('2', DATE '2020-01-01')")
    banco.execute("INSERT INTO ficha_extras VALUES "
                  "('1', NULL, 'clarke', 'pePI', '2026-08-25'), "
                  "('2', NULL, 'clarke', 'pePI', '2026-08-25')")
    monkeypatch.setattr(consulta, "con", lambda: banco)

    amostra = amostrar_processos("clarke", tamanho=10, dias_recentes=45)

    assert {a["numero_inpi"] for a in amostra} == {"1", "2"}
    recentes = {a["numero_inpi"] for a in amostra if a["recente"]}
    assert recentes == {"1"}
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `python -m pytest inpi/test_validar_plataforma_nova.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'inpi.validar_plataforma_nova'`

- [ ] **Step 3: Implementar o script de validação**

```python
# inpi/validar_plataforma_nova.py
"""Valida a plataforma nova (Modulo de Servicos de Patentes) contra uma
amostra de processos ja cobertos pelo pePI, ANTES de desligar o pePI+Tor
(ver docs/superpowers/specs/2026-09-04-inpi-plataforma-nova-design.md,
Stream A). Mede taxa de erro e cobertura de depositos recentes -- hipotese a
testar: a plataforma nova pode nao ter indexado ainda pedidos depositados
nos ultimos dias/semanas (o pePI, sistema legado de tramitacao, teria).

Rode manualmente: python -m inpi.validar_plataforma_nova
Precisa de INPI_PAG_LOGIN/INPI_PAG_PASSWORD no .env -- rede real, conta
dedicada, NAO roda em teste automatizado.
"""

from __future__ import annotations

import random
import time
from datetime import date, timedelta

from inpi.consulta import _linhas
from inpi.plataforma_nova import ClientePlataformaNova, PlataformaNovaError


def amostrar_processos(escritorio_canonico: str | None, tamanho: int,
                       dias_recentes: int) -> list[dict]:
    """Amostra numero_inpi ja coletados pelo pePI (tabela ficha_extras), ate
    metade de `tamanho` de cada grupo -- 'recentes' (deposito nos ultimos
    `dias_recentes` dias) e 'antigos' -- pra medir cobertura das duas
    populacoes separadamente, nao so uma media que esconde o problema."""
    corte = (date.today() - timedelta(days=dias_recentes)).isoformat()
    filtro = " AND fe.escritorio_canonico = ?" if escritorio_canonico else ""
    params_extra = [escritorio_canonico] if escritorio_canonico else []

    # strftime antes de comparar, nao DATE bruto contra parametro VARCHAR --
    # mesmo padrao de inpi/anuidades_pagas.py (comparar DATE ao ? direto e
    # ambiguo pro driver duckdb quando o parametro chega como str do Python).
    recentes = _linhas(
        f"""SELECT fe.numero_inpi, b.data_deposito
            FROM ficha_extras fe JOIN biblio b USING (numero_inpi)
            WHERE strftime(b.data_deposito, '%Y-%m-%d') >= ?{filtro}""",
        [corte, *params_extra],
    )
    antigos = _linhas(
        f"""SELECT fe.numero_inpi, b.data_deposito
            FROM ficha_extras fe JOIN biblio b USING (numero_inpi)
            WHERE strftime(b.data_deposito, '%Y-%m-%d') < ?{filtro}""",
        [corte, *params_extra],
    )
    metade = max(1, tamanho // 2)
    amostra = (random.sample(recentes, min(metade, len(recentes)))
              + random.sample(antigos, min(metade, len(antigos))))
    for item in amostra:
        item["recente"] = str(item["data_deposito"]) >= corte
    return amostra


def montar_relatorio(resultados: list[dict]) -> dict:
    """Agrega o resultado por-processo em taxas. Cada item de `resultados`:
    {numero_inpi, recente, sucesso, indexado, erro}."""
    def _taxa(grupo: list[dict]) -> dict:
        total = len(grupo)
        if total == 0:
            return {"total": 0, "sucesso": 0, "indexado": 0,
                    "taxa_sucesso": None, "taxa_indexado": None}
        sucesso = sum(1 for r in grupo if r["sucesso"])
        indexado = sum(1 for r in grupo if r.get("indexado"))
        return {"total": total, "sucesso": sucesso, "indexado": indexado,
                "taxa_sucesso": round(sucesso / total, 3),
                "taxa_indexado": round(indexado / total, 3)}

    recentes = [r for r in resultados if r["recente"]]
    antigos = [r for r in resultados if not r["recente"]]
    return {
        "total_amostrado": len(resultados),
        "recentes": _taxa(recentes),
        "antigos": _taxa(antigos),
        "erros_exemplo": [r["erro"] for r in resultados if r.get("erro")][:10],
    }


def rodar_validacao(cliente: ClientePlataformaNova, escritorio_canonico: str | None = None,
                    tamanho: int = 1000, dias_recentes: int = 45) -> dict:
    """Roda a amostra contra a plataforma nova de verdade. Nao chamar em
    teste automatizado -- rede real, conta dedicada."""
    amostra = amostrar_processos(escritorio_canonico, tamanho, dias_recentes)
    resultados = []
    for item in amostra:
        numero_inpi = item["numero_inpi"]
        entrada = {"numero_inpi": numero_inpi, "recente": item["recente"],
                   "sucesso": False, "indexado": None, "erro": None}
        try:
            biblio = cliente.get_bibliographic_data(numero_inpi)
            entrada["sucesso"] = True
            entrada["indexado"] = bool(biblio)
        except PlataformaNovaError as exc:
            entrada["erro"] = str(exc)
        resultados.append(entrada)
        time.sleep(0.2)  # nao martelar a API numa rajada sem medir throughput antes
    return montar_relatorio(resultados)


def main() -> int:
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    login = os.environ["INPI_PAG_LOGIN"]
    senha = os.environ["INPI_PAG_PASSWORD"]
    cliente = ClientePlataformaNova(login, senha)
    relatorio = rodar_validacao(cliente)
    print(relatorio)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `python -m pytest inpi/test_validar_plataforma_nova.py -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Commit**

```bash
git add inpi/validar_plataforma_nova.py inpi/test_validar_plataforma_nova.py
git commit -m "feat(inpi): script de validacao de volume da plataforma nova vs pePI"
```

- [ ] **Step 6: Rodar a validação de verdade (manual, fora do CI) e decidir o corte**

Adicionar `INPI_PAG_LOGIN`/`INPI_PAG_PASSWORD` (conta dedicada, cadastro tipo "Cliente" em `meu.inpi.gov.br`) ao `.env` local, depois:

Run: `python -m inpi.validar_plataforma_nova`

Ler `taxa_sucesso`/`taxa_indexado` de `recentes` vs `antigos` no relatório impresso. Só desligar o cron do pePI+Tor (`inpi/coleta_ficha_extras.py`) depois de `taxa_sucesso` aceitável (sem 429/403 em massa) E `taxa_indexado` de `recentes` equivalente à de `antigos` — se `recentes` vier sistematicamente mais baixo, confirma a hipótese do usuário (depósitos recentes só no pePI) e o pePI fica permanentemente como fonte pra esse recorte, não só fallback temporário.

---

### Task 4: Tabela `estatistica_nacional` no ingest.py + sync incremental

**Files:**
- Modify: `inpi/ingest.py`
- Modify: `vigilancia/sync_motherduck.py:37-38`
- Test: `inpi/test_ingest_estatistica_nacional.py`

**Interfaces:**
- Produces: `_mescla_estatistica_nacional(con) -> None` em `inpi/ingest.py`, lendo `inpi/referencias/estatistica-nacional.csv` (colunas: `ano, tipo_ativo, sub_tipo, tipo_patente, via_entrada, origem, pais, uf, regiao, campo_tecnologico, decisao, ano_decisao, depositos, concessoes, n_decisoes, n_vigentes, coletado_em`); cria/substitui a tabela `estatistica_nacional`.

- [ ] **Step 1: Escrever o teste (falhando)**

```python
# inpi/test_ingest_estatistica_nacional.py
from __future__ import annotations

import csv

import duckdb

from inpi.ingest import _mescla_estatistica_nacional


def test_mescla_estatistica_nacional_cria_tabela_a_partir_do_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "estatistica-nacional.csv"
    campos = ["ano", "tipo_ativo", "sub_tipo", "tipo_patente", "via_entrada",
             "origem", "pais", "uf", "regiao", "campo_tecnologico", "decisao",
             "ano_decisao", "depositos", "concessoes", "n_decisoes",
             "n_vigentes", "coletado_em"]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerow({"ano": 2024, "tipo_ativo": "Patentes", "sub_tipo": "Patente de Invenção",
                   "tipo_patente": "Patente de Invenção", "via_entrada": "PCT",
                   "origem": "Residente", "pais": "Brasil", "uf": "Diversas UF",
                   "regiao": "Brasil", "campo_tecnologico": "Química",
                   "decisao": "Concessão", "ano_decisao": 2024, "depositos": 100,
                   "concessoes": 40, "n_decisoes": 40, "n_vigentes": 40,
                   "coletado_em": "2026-09-04"})

    import inpi.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "ESTATISTICA_NACIONAL", csv_path)

    con = duckdb.connect(":memory:")
    _mescla_estatistica_nacional(con)

    linhas = con.execute("SELECT ano, tipo_ativo, depositos FROM estatistica_nacional").fetchall()
    assert linhas == [(2024, "Patentes", 100)]


def test_mescla_estatistica_nacional_sem_csv_nao_cria_tabela(tmp_path, monkeypatch):
    import inpi.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "ESTATISTICA_NACIONAL", tmp_path / "nao-existe.csv")

    con = duckdb.connect(":memory:")
    _mescla_estatistica_nacional(con)

    tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert "estatistica_nacional" not in tabelas
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest inpi/test_ingest_estatistica_nacional.py -v`
Expected: FAIL com `ImportError: cannot import name '_mescla_estatistica_nacional'`

- [ ] **Step 3: Implementar em `inpi/ingest.py`**

Adicionar após a constante `FICHA_EXTRAS = RAIZ / "referencias" / "ficha-extras.csv"` (linha 30):

```python
ESTATISTICA_NACIONAL = RAIZ / "referencias" / "estatistica-nacional.csv"
```

Adicionar nova função, logo depois de `_mescla_ficha_extras` (após a linha 406, antes de `def main()`):

```python
def _mescla_estatistica_nacional(con) -> None:
    """Cria a tabela estatistica_nacional a partir do CSV baixado do Portal de
    Estatisticas publico do INPI (inpi/estatistica_publica.py) -- dataset
    AGREGADO NACIONAL (nao por processo), usado por inpi_estatistica_nacional.
    Fonte externa ao dump semanal de dados abertos: se o CSV nao existir ainda
    (coleta nao rodou), a tabela simplesmente nao e criada -- mesma regra de
    tolerancia de _mescla_ficha_extras."""
    if not ESTATISTICA_NACIONAL.exists():
        return
    t0 = time.time()
    caminho = ESTATISTICA_NACIONAL.as_posix()
    con.execute(f"""
      CREATE OR REPLACE TABLE estatistica_nacional AS
      SELECT DISTINCT * FROM read_csv('{caminho}', header=true, delim=',',
        quote='"', escape='"',
        columns={{
          'ano': 'INTEGER', 'tipo_ativo': 'VARCHAR', 'sub_tipo': 'VARCHAR',
          'tipo_patente': 'VARCHAR', 'via_entrada': 'VARCHAR', 'origem': 'VARCHAR',
          'pais': 'VARCHAR', 'uf': 'VARCHAR', 'regiao': 'VARCHAR',
          'campo_tecnologico': 'VARCHAR', 'decisao': 'VARCHAR',
          'ano_decisao': 'INTEGER', 'depositos': 'INTEGER', 'concessoes': 'INTEGER',
          'n_decisoes': 'INTEGER', 'n_vigentes': 'INTEGER', 'coletado_em': 'VARCHAR'
        }})
    """)
    n = con.execute("SELECT count(*) FROM estatistica_nacional").fetchone()[0]
    print(f"  estatistica_nacional {n:>7,} linhas   {time.time() - t0:5.1f}s", flush=True)
```

Em `main()`, logo após a linha `_mescla_ficha_extras(con)` (linha 454):

```python
    _mescla_estatistica_nacional(con)
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `python -m pytest inpi/test_ingest_estatistica_nacional.py -v`
Expected: PASS (2 testes)

- [ ] **Step 5: Adicionar a tabela nova ao sync incremental do MotherDuck**

Em `vigilancia/sync_motherduck.py`, linhas 37-38, mudar:

```python
TABELAS_DERIVADAS = ("titulares", "escritorios", "identidade_escritorio",
                     "ficha_extras", "ficha_peticoes", "ficha_anuidades")
```

para:

```python
TABELAS_DERIVADAS = ("titulares", "escritorios", "identidade_escritorio",
                     "ficha_extras", "ficha_peticoes", "ficha_anuidades",
                     "estatistica_nacional")
```

- [ ] **Step 6: Rodar a suíte completa de `vigilancia` pra garantir que nada quebrou**

Run: `python -m pytest vigilancia/ -q`
Expected: PASS (todos os testes existentes continuam passando — `sincronizar_incremental` já trata tabela ausente como "modo completo", `estatistica_nacional` sem CSV simplesmente não aparece em `SHOW TABLES` e é pulada, ver linha `if tabela not in tabelas_novo: continue`)

- [ ] **Step 7: Commit**

```bash
git add inpi/ingest.py inpi/test_ingest_estatistica_nacional.py vigilancia/sync_motherduck.py
git commit -m "feat(inpi): tabela estatistica_nacional no ingest + sync incremental MotherDuck"
```

---

### Task 5: Coletor do Portal de Estatísticas (Playwright → CSV)

**Files:**
- Create: `inpi/estatistica_publica.py`
- Test: `inpi/test_estatistica_publica.py`
- Modify: `pyproject.toml:10-26` (adicionar `playwright`)

**Interfaces:**
- Consumes: nenhuma interface interna (módulo raiz de Stream B).
- Produces: `gravar_csv(linhas_js: list[dict], destino: Path = CSV_SAIDA, coletado_em: str | None = None) -> int`; `_linha_csv(linha_js: dict, coletado_em: str) -> dict` (schema alinhado com `_mescla_estatistica_nacional` da Task 4); `main() -> int` (roda `_buscar_pivot_data()` de verdade — rede/Chromium, não testado).

- [ ] **Step 1: Adicionar Playwright à dependência**

Em `pyproject.toml`, dentro de `dependencies = [...]` (linha 10-26), adicionar `"playwright",` à lista. Depois:

Run: `pip install -e .`
Run: `python -m playwright install chromium`
Expected: Playwright e o binário do Chromium instalados (passo manual único por máquina/CI, não faz parte do teste automatizado).

- [ ] **Step 2: Escrever os testes (falhando)**

```python
# inpi/test_estatistica_publica.py
from __future__ import annotations

import csv

from inpi.estatistica_publica import _CAMPOS, _linha_csv, gravar_csv


def test_linha_csv_traduz_camelcase_pra_snake_case():
    linha_js = {
        "ano": 2000, "tipoAtivo": "Patentes", "subTipo": "Patente de Invenção",
        "tipoPatente": "Patente de Invenção", "viaEntrada": "PCT",
        "origem": "Residente", "pais": "Brasil", "uf": "Diversas UF",
        "regiao": "Brasil", "campoTecnologico": "Química", "decisao": "Concessão",
        "anoDecisao": 2000, "depositos": 283, "concessoes": 91,
        "nDecisoes": 91, "nVigentes": 0,
    }
    linha = _linha_csv(linha_js, coletado_em="2026-09-04")

    assert linha["ano"] == 2000
    assert linha["tipo_ativo"] == "Patentes"
    assert linha["campo_tecnologico"] == "Química"
    assert linha["n_vigentes"] == 0
    assert linha["coletado_em"] == "2026-09-04"


def test_linha_csv_com_campo_ausente_usa_string_vazia():
    linha = _linha_csv({"ano": 2000, "tipoAtivo": "Marcas"}, coletado_em="2026-09-04")
    assert linha["origem"] == ""
    assert linha["campo_tecnologico"] == ""


def test_gravar_csv_escreve_cabecalho_e_linhas(tmp_path):
    destino = tmp_path / "saida.csv"
    linhas_js = [
        {"ano": 2000, "tipoAtivo": "Patentes", "depositos": 283, "concessoes": 91,
         "nDecisoes": 91, "nVigentes": 0},
        {"ano": 2001, "tipoAtivo": "Patentes", "depositos": 300, "concessoes": 95,
         "nDecisoes": 95, "nVigentes": 5},
    ]

    n = gravar_csv(linhas_js, destino=destino, coletado_em="2026-09-04")

    assert n == 2
    with destino.open(encoding="utf-8") as fh:
        linhas = list(csv.DictReader(fh))
    assert [c for c in linhas[0]] == _CAMPOS
    assert linhas[0]["ano"] == "2000"
    assert linhas[1]["depositos"] == "300"
```

- [ ] **Step 3: Rodar os testes e confirmar que falham**

Run: `python -m pytest inpi/test_estatistica_publica.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'inpi.estatistica_publica'`

- [ ] **Step 4: Implementar o coletor**

```python
# inpi/estatistica_publica.py
"""Baixa o dataset agregado nacional do Portal de Estatisticas do INPI
(servicos.estatistica.inpi.gov.br), publico, sem login. Os numeros vem
pre-decodificados em window.pivotData depois que a pagina carrega os
scripts db-data.js/db-engine.js -- o formato de codificacao colunar desses
arquivos NAO foi decifrado (ver docs/pesquisa/inpi_plataforma_nova.md), entao
usamos um Chromium headless (Playwright) so pra deixar o proprio JS da pagina
fazer esse trabalho, em vez de reimplementar o decoder em Python.

ponytail: dependencia pesada (Chromium) so pra ler uma variavel JS ja
decodificada -- se o formato de db-data.js for decifrado depois, trocar por
parse direto em Python e derrubar essa dependencia.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent
CSV_SAIDA = RAIZ / "referencias" / "estatistica-nacional.csv"
URL = "https://servicos.estatistica.inpi.gov.br/"

_CAMPOS = ["ano", "tipo_ativo", "sub_tipo", "tipo_patente", "via_entrada",
          "origem", "pais", "uf", "regiao", "campo_tecnologico", "decisao",
          "ano_decisao", "depositos", "concessoes", "n_decisoes", "n_vigentes",
          "coletado_em"]

_MAPA_CAMPOS = {
    "ano": "ano", "tipoAtivo": "tipo_ativo", "subTipo": "sub_tipo",
    "tipoPatente": "tipo_patente", "viaEntrada": "via_entrada",
    "origem": "origem", "pais": "pais", "uf": "uf", "regiao": "regiao",
    "campoTecnologico": "campo_tecnologico", "decisao": "decisao",
    "anoDecisao": "ano_decisao", "depositos": "depositos",
    "concessoes": "concessoes", "nDecisoes": "n_decisoes",
    "nVigentes": "n_vigentes",
}


def _linha_csv(linha_js: dict[str, Any], coletado_em: str) -> dict[str, Any]:
    """Traduz uma linha de window.pivotData (chaves camelCase, como o JS da
    pagina produz) pro schema snake_case do CSV/DuckDB (inpi/ingest.py). Chave
    ausente vira string vazia -- linha de window.pivotData pode nao ter todas
    as dimensoes (ex.: 'origem' so existe pra Patentes, nao pra Marcas)."""
    saida: dict[str, Any] = {c: "" for c in _CAMPOS}
    for chave_js, chave_csv in _MAPA_CAMPOS.items():
        if chave_js in linha_js and linha_js[chave_js] is not None:
            saida[chave_csv] = linha_js[chave_js]
    saida["coletado_em"] = coletado_em
    return saida


def _buscar_pivot_data() -> list[dict[str, Any]]:
    """Abre a pagina publica num Chromium headless e le window.pivotData
    depois que a pagina termina de carregar. Rede real -- so chamada por
    main(), nunca em teste automatizado (import de playwright fica local a
    esta funcao pra nao exigir o pacote instalado so pra rodar os testes)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page()
        pagina.goto(URL, wait_until="networkidle")
        dados = pagina.evaluate("window.pivotData")
        navegador.close()
        return dados


def gravar_csv(linhas_js: list[dict[str, Any]], destino: Path = CSV_SAIDA,
              coletado_em: str | None = None) -> int:
    """Escreve o CSV a partir de linhas ja obtidas (testavel sem rede/
    navegador -- separado de _buscar_pivot_data de proposito). Devolve o
    numero de linhas gravadas."""
    coletado_em = coletado_em or date.today().isoformat()
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_CAMPOS, lineterminator="\n")
        w.writeheader()
        for linha_js in linhas_js:
            w.writerow(_linha_csv(linha_js, coletado_em))
    return len(linhas_js)


def main() -> int:
    linhas_js = _buscar_pivot_data()
    n = gravar_csv(linhas_js)
    print(f"estatistica-nacional.csv: {n:,} linhas")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

- [ ] **Step 5: Rodar os testes e confirmar que passam**

Run: `python -m pytest inpi/test_estatistica_publica.py -v`
Expected: PASS (4 testes)

- [ ] **Step 6: Commit**

```bash
git add inpi/estatistica_publica.py inpi/test_estatistica_publica.py pyproject.toml
git commit -m "feat(inpi): coletor do Portal de Estatisticas publico via Playwright"
```

- [ ] **Step 7: Rodar a coleta de verdade (manual, fora do CI)**

Run: `python -m inpi.estatistica_publica`
Expected: `inpi/referencias/estatistica-nacional.csv` criado com milhares de linhas (o dataset real tem ~6078 linhas, ver `docs/pesquisa/inpi_plataforma_nova.md`). Depois rodar `python inpi/ingest.py` (sem `--baixar`, reaproveitando os CSVs de dados abertos já baixados) pra materializar `estatistica_nacional` no `.duckdb` local.

---

### Task 6: Tool MCP `inpi_estatistica_nacional`

**Files:**
- Create: `inpi/estatistica_nacional.py`
- Modify: `inpi/inpi_mcp.py:96` (registro da tool)
- Test: `inpi/test_estatistica_nacional.py`

**Interfaces:**
- Consumes: `_linhas(sql, params) -> list[dict]`, `_tem_tabela(nome) -> bool` de `inpi.consulta`; tabela `estatistica_nacional` (Task 4).
- Produces: `inpi_estatistica_nacional(ano_inicial=None, ano_final=None, tipo_ativo=None, campo_tecnologico=None, regiao=None, decisao=None) -> dict`.

**Desvio deliberado do spec:** o spec (`docs/superpowers/specs/2026-09-04-inpi-plataforma-nova-design.md`, Stream B) descreve "`inpi_mercado`/`landscape_*` passam a ler dessa tabela como fonte adicional, sem mudar a interface". Ao inspecionar `inpi/estatistica.py` (whitelist `_DATASETS`) nesta plan, as tools existentes giram em torno de escritório/titular/CPC — `estatistica_nacional` não tem essas dimensões (é agregado nacional por região/campo tecnológico). Forçar esse dado dentro do formato existente exigiria inventar colunas fictícias de escritório/titular. Optei por uma tool nova e dedicada em vez de uma mudança silenciosa de fonte por trás de uma tool com contrato incompatível — mais simples e mais honesto sobre o que o dado é.

- [ ] **Step 1: Escrever o teste (falhando)**

```python
# inpi/test_estatistica_nacional.py
from __future__ import annotations

import duckdb

import inpi.consulta as consulta
from inpi.estatistica_nacional import inpi_estatistica_nacional


def _banco_fixture():
    con = duckdb.connect(":memory:")
    con.execute("""
      CREATE TABLE estatistica_nacional (
        ano INTEGER, tipo_ativo VARCHAR, sub_tipo VARCHAR, tipo_patente VARCHAR,
        via_entrada VARCHAR, origem VARCHAR, pais VARCHAR, uf VARCHAR,
        regiao VARCHAR, campo_tecnologico VARCHAR, decisao VARCHAR,
        ano_decisao INTEGER, depositos INTEGER, concessoes INTEGER,
        n_decisoes INTEGER, n_vigentes INTEGER, coletado_em VARCHAR
      )
    """)
    con.execute("""
      INSERT INTO estatistica_nacional VALUES
        (2023, 'Patentes', NULL, NULL, NULL, NULL, NULL, NULL, 'Sudeste',
         'Química', 'Concessão', 2023, 100, 40, 40, 40, '2026-09-04'),
        (2023, 'Patentes', NULL, NULL, NULL, NULL, NULL, NULL, 'Sudeste',
         'Mecânica', 'Concessão', 2023, 50, 20, 20, 20, '2026-09-04'),
        (2024, 'Marcas', NULL, NULL, NULL, NULL, NULL, NULL, 'Sul',
         NULL, 'Concessão', 2024, 200, 150, 150, 150, '2026-09-04')
    """)
    return con


def test_agrega_por_ano_sem_filtro(monkeypatch):
    monkeypatch.setattr(consulta, "con", _banco_fixture)

    r = inpi_estatistica_nacional()

    assert r["por_ano"] == [
        {"ano": 2023, "depositos": 150, "concessoes": 60, "n_decisoes": 60, "n_vigentes": 60},
        {"ano": 2024, "depositos": 200, "concessoes": 150, "n_decisoes": 150, "n_vigentes": 150},
    ]
    assert r["total_depositos"] == 350


def test_filtra_por_tipo_ativo_e_campo_tecnologico(monkeypatch):
    monkeypatch.setattr(consulta, "con", _banco_fixture)

    r = inpi_estatistica_nacional(tipo_ativo="Patentes", campo_tecnologico="Química")

    assert r["por_ano"] == [
        {"ano": 2023, "depositos": 100, "concessoes": 40, "n_decisoes": 40, "n_vigentes": 40},
    ]
    assert r["filtros"] == {"tipo_ativo": "Patentes", "campo_tecnologico": "Química"}


def test_tabela_ausente_devolve_erro_amigavel(monkeypatch):
    con_vazio = duckdb.connect(":memory:")
    monkeypatch.setattr(consulta, "con", lambda: con_vazio)

    r = inpi_estatistica_nacional()

    assert r["erro"] is True
    assert "estatistica_nacional" in r["mensagem"]
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest inpi/test_estatistica_nacional.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'inpi.estatistica_nacional'`

- [ ] **Step 3: Implementar a tool**

```python
# inpi/estatistica_nacional.py
"""Consulta o dataset agregado nacional do INPI (Portal de Estatisticas,
servicos.estatistica.inpi.gov.br) -- ano/tipo de ativo/campo tecnologico/
regiao/decisao, com depositos/concessoes/decisoes/vigencias.

Distinto de inpi_estatistica (soma/media sobre ledgers POR ESCRITORIO/titular
coletados do pePI, inpi/estatistica.py): este e dado NACIONAL agregado, sem
recorte por escritorio/titular, carregado pela tabela estatistica_nacional
(inpi/estatistica_publica.py + inpi/ingest.py)."""

from __future__ import annotations

from inpi.consulta import _linhas, _tem_tabela
from inpi.mcp_app import mcp

_FILTROS = {
    "ano_inicial": "ano >= ?",
    "ano_final": "ano <= ?",
    "tipo_ativo": "tipo_ativo = ?",
    "campo_tecnologico": "campo_tecnologico = ?",
    "regiao": "regiao = ?",
    "decisao": "decisao = ?",
}


@mcp.tool()
def inpi_estatistica_nacional(
    ano_inicial: int | None = None, ano_final: int | None = None,
    tipo_ativo: str | None = None, campo_tecnologico: str | None = None,
    regiao: str | None = None, decisao: str | None = None,
) -> dict:
    """Serie agregada nacional de depositos/concessoes por ano, do Portal de
    Estatisticas do INPI (dado publico, todo o pais -- NAO e por escritorio
    ou titular).

    USE QUANDO: a pergunta for sobre volume nacional/setorial (ex.: "quantos
    depositos de patente em Quimica em 2023", "concessoes por regiao"). Para
    o desempenho de UM escritorio/titular especifico, use inpi_mercado ou
    inpi_estatistica -- ferramentas diferentes, granularidade diferente.

    Args:
        ano_inicial/ano_final: filtro de ano de deposito (inclusive).
        tipo_ativo: 'Patentes', 'Marcas', 'Desenho Industrial', 'Contratos de
            Tecnologia', 'Programa de Computador', 'Topografia de CI'.
        campo_tecnologico: so relevante para Patentes (ex.: 'Quimica').
        regiao: regiao do titular/depositante.
        decisao: 'Concessao', 'Indeferimento', 'Arquivamento', etc.
    """
    if not _tem_tabela("estatistica_nacional"):
        return {"erro": True, "mensagem": (
            "Tabela estatistica_nacional ausente -- rode "
            "inpi/estatistica_publica.py e depois inpi/ingest.py.")}

    valores = {"ano_inicial": ano_inicial, "ano_final": ano_final,
              "tipo_ativo": tipo_ativo, "campo_tecnologico": campo_tecnologico,
              "regiao": regiao, "decisao": decisao}
    cond, params = [], []
    for chave, sql in _FILTROS.items():
        if valores[chave] is not None:
            cond.append(sql)
            params.append(valores[chave])
    where = ("WHERE " + " AND ".join(cond)) if cond else ""

    linhas = _linhas(
        f"""SELECT ano, sum(depositos) AS depositos, sum(concessoes) AS concessoes,
                   sum(n_decisoes) AS n_decisoes, sum(n_vigentes) AS n_vigentes
            FROM estatistica_nacional {where}
            GROUP BY ano ORDER BY ano""",
        params,
    )
    return {
        "filtros": {k: v for k, v in valores.items() if v is not None},
        "por_ano": linhas,
        "total_depositos": sum(r["depositos"] or 0 for r in linhas),
        "total_concessoes": sum(r["concessoes"] or 0 for r in linhas),
        "fonte": "Portal de Estatisticas do INPI (servicos.estatistica.inpi.gov.br) "
                 "-- dado agregado nacional publico, atualizado por coleta periodica "
                 "(nao e o dump semanal de dados abertos).",
    }
```

Em `inpi/inpi_mcp.py`, logo após a linha 92 (`from inpi.anuidades_pagas import inpi_anuidades_pagas  # noqa: F401`), adicionar:

```python
from inpi.estatistica_nacional import inpi_estatistica_nacional  # noqa: F401
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `python -m pytest inpi/test_estatistica_nacional.py -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Rodar a suíte inteira de `inpi/` pra garantir que o registro da tool não quebrou nada**

Run: `python -m pytest inpi/ -q`
Expected: PASS (todos os testes existentes + os novos desta plan)

- [ ] **Step 6: Commit**

```bash
git add inpi/estatistica_nacional.py inpi/test_estatistica_nacional.py inpi/inpi_mcp.py
git commit -m "feat(inpi): tool inpi_estatistica_nacional sobre o Portal de Estatisticas"
```

---

## Fora de escopo deste plano (documentado no spec, não implementado aqui)

- Matrix de GitHub Actions no repo público separado pra rodar o backlog completo — só depois que a Task 3/Step 6 (validação de volume) passar.
- Desligar `inpi/coleta_ficha_extras.py`/`inpi/tor_proxy.py` — decisão pós-validação, não uma task de código.
- Mapear "Eventos de Pedido" pra `ficha_peticoes` — deliberadamente adiado (ver docstring de `inpi/coleta_plataforma_nova.py`) até confirmar se é o mesmo conceito de "Peticoes/Servicos" do pePI.
- Cron/agendamento automático do `inpi/estatistica_publica.py` (ex.: GitHub Actions semanal) — este plano entrega o script rodável manualmente; agendar é configuração de infraestrutura, não código novo.
