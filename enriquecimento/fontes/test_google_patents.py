from __future__ import annotations

import enriquecimento.fontes.google_patents as gp
from enriquecimento.fontes.google_patents import (
    _candidatos_doc_id,
    buscar_claims,
    detectar_jurisdicao,
    extrair_citacoes,
    extrair_claims,
    quadro_reivindicatorio,
)

# Fixtures no formato do HTML BRUTO real (confirmado ao vivo na Fase 0/5 --
# ver docstring de extrair_claims/extrair_citacoes: a tag <patent-text> só
# existe pós-hidratação do Polymer no navegador, não na resposta HTTP crua).

HTML_COM_CLAIMS = """
<html><body>
<section itemprop="description"><div>texto de descricao, nao e reivindicacao</div></section>
<section itemprop="claims" itemscope>
<h2>Claims (<span itemprop="count">2</span>)</h2>
<div itemprop="content" html><div class="claims">
<div class="claim"><div id="c0001" num="0001" class="claim">
<div class="claim-text">1 .) "LUVA BIODEGRADAVEL", caracterizada por compreender uma camada de papel.</div>
</div></div>
<div class="claim"><div id="c0002" num="0002" class="claim">
<div class="claim-text">2 .) A luva de acordo com a reivindicacao 1, caracterizada por ter tira absorvente.</div>
</div></div>
</div></div>
</section>
</body></html>
"""

HTML_SEM_CLAIMS = """
<html><body>
<section itemprop="description"><div>so descricao, sem secao de claims nesta pagina</div></section>
</body></html>
"""

HTML_COM_CITACOES = """
<html><body>
<section>
<h2>Patent Citations (2)</h2>
<table><thead><tr><th>Publication number</th></tr></thead>
<tbody>
<tr itemprop="backwardReferences" itemscope repeat>
  <td><a href="/patent/US1234567A/en"><span itemprop="publicationNumber">US1234567A</span></a></td>
</tr>
<tr itemprop="backwardReferencesOrig" itemscope repeat>
  <td><a href="/patent/US1234567A/en"><span itemprop="publicationNumber">US1234567A</span></a></td>
</tr>
<tr itemprop="backwardReferences" itemscope repeat>
  <td><a href="/patent/EP7654321A1/en"><span itemprop="publicationNumber">EP7654321A1</span></a></td>
</tr>
</tbody></table>
</section>
<section>
<h2>Cited By (1)</h2>
<table><thead><tr><th>Publication number</th></tr></thead>
<tbody>
<tr itemprop="forwardReferencesOrig" itemscope repeat>
  <td><a href="/patent/US9999999B2/en"><span itemprop="publicationNumber">US9999999B2</span></a></td>
</tr>
</tbody></table>
</section>
</body></html>
"""


def test_extrai_claims_da_secao_correta():
    claims = extrair_claims(HTML_COM_CLAIMS)

    assert claims is not None
    assert len(claims) == 2
    assert claims[0]["numero"] == 1
    assert "papel" in claims[0]["texto"]
    assert claims[1]["numero"] == 2


def test_extrai_claims_devolve_none_sem_secao():
    assert extrair_claims(HTML_SEM_CLAIMS) is None


def test_extrai_citacoes_separa_citando_e_citada_por():
    citacoes = extrair_citacoes(HTML_COM_CITACOES)

    citando = [c for c in citacoes if c["tipo"] == "citando"]
    citada_por = [c for c in citacoes if c["tipo"] == "citada_por"]

    assert {c["doc_citado"] for c in citando} == {"US1234567A", "EP7654321A1"}
    assert {c["doc_citado"] for c in citada_por} == {"US9999999B2"}


def test_extrai_citacoes_dedupe_orig_e_normalizada():
    """US1234567A aparece em 'backwardReferences' e 'backwardReferencesOrig'
    -- e a MESMA citacao, so nao pode contar duas vezes."""
    citacoes = extrair_citacoes(HTML_COM_CITACOES)
    citando_us1234567a = [c for c in citacoes if c["doc_citado"] == "US1234567A"]
    assert len(citando_us1234567a) == 1


def test_quadro_reivindicatorio_texto_vazio():
    assert quadro_reivindicatorio("") == []


def test_quadro_reivindicatorio_sem_numeracao_reconhecida():
    resultado = quadro_reivindicatorio("um texto qualquer sem marcador numerico")
    assert resultado == [{"numero": None, "texto": "um texto qualquer sem marcador numerico"}]


# Regressao do bug real (plano de refino 2026-08): _candidatos_doc_id forcava
# prefixo 'BR' em QUALQUER numero -- 'US6421675B1' virava 'BRUS6421675B1A2',
# que nunca existe. A pagina US existe de verdade no Google Patents
# (confirmado ao vivo na auditoria, HTTP 200 com secao de claims).


def test_detecta_jurisdicao_por_prefixo():
    assert detectar_jurisdicao("US6421675B1") == "US"
    assert detectar_jurisdicao("EP1234567") == "EP"
    assert detectar_jurisdicao("WO2020123456A1") == "WO"
    assert detectar_jurisdicao("102022010731") == "BR"  # sem prefixo -- BR normalizado


def test_candidatos_doc_id_us_nao_prefixa_br():
    candidatos = _candidatos_doc_id("US6421675B1")
    assert all(not c.startswith("BRUS") for c in candidatos)
    # kind ja embutido no numero digitado entra primeiro, tentado sem adivinhar.
    assert candidatos[0] == "US6421675B1"


def test_candidatos_doc_id_us_sem_kind_varre_kinds_comuns():
    candidatos = _candidatos_doc_id("US6421675")
    assert candidatos[0] == "US6421675B1"
    assert "US6421675B2" in candidatos
    assert all(c.startswith("US6421675") for c in candidatos)


def test_candidatos_doc_id_br_mantem_comportamento_anterior():
    candidatos = _candidatos_doc_id("102022010731")
    assert candidatos[0] == "BR102022010731A2"
    assert all(c.startswith("BR102022010731") for c in candidatos)


def test_candidatos_doc_id_ep_e_wo():
    assert _candidatos_doc_id("EP1234567")[0] == "EP1234567B1"
    assert _candidatos_doc_id("WO2020123456A1")[0] == "WO2020123456A1"


HTML_COM_CLAIMS_US = """
<html><body>
<section itemprop="claims" itemscope>
<h2>Claims (<span itemprop="count">1</span>)</h2>
<div itemprop="content" html><div class="claims">
<div class="claim"><div id="c0001" num="0001" class="claim">
<div class="claim-text">1. A biodegradable glove comprising a paper layer.</div>
</div></div>
</div></div>
</section>
</body></html>
"""


def test_extrai_claims_us_mesma_secao_que_br():
    """Mesmo parser serve para qualquer jurisdicao -- a secao 'claims' e
    identica na estrutura do HTML, so muda o doc_id que a busca resolve."""
    claims = extrair_claims(HTML_COM_CLAIMS_US)

    assert claims is not None
    assert len(claims) == 1
    assert "biodegradable" in claims[0]["texto"]


# Regressao de um segundo bug real, achado AO VIVO verificando o fix do
# primeiro (US6421675B1): a pagina '/pt' do Google Patents para um documento
# US devolve HTTP 200 mas SEM a secao <section itemprop="claims"> no HTML
# bruto -- so a variante '/en' (idioma original da publicacao) tem a secao
# completa. Sem idioma default por jurisdicao, todo claim chart US/EP/WO
# falharia silenciosamente com 'sem secao de Claims reconhecida', mesmo com
# _candidatos_doc_id corrigido.


def test_buscar_claims_usa_pt_para_br_por_padrao(monkeypatch):
    idiomas_chamados = []

    def _fake_buscar_pagina(cid, idioma):
        idiomas_chamados.append(idioma)
        return None  # sem resposta -- so queremos capturar o idioma escolhido

    monkeypatch.setattr(gp, "_buscar_pagina", _fake_buscar_pagina)
    buscar_claims("102022010731")

    assert idiomas_chamados and all(i == "pt" for i in idiomas_chamados)


def test_buscar_claims_usa_en_para_us_por_padrao(monkeypatch):
    idiomas_chamados = []

    def _fake_buscar_pagina(cid, idioma):
        idiomas_chamados.append(idioma)
        return None

    monkeypatch.setattr(gp, "_buscar_pagina", _fake_buscar_pagina)
    buscar_claims("US6421675B1")

    assert idiomas_chamados and all(i == "en" for i in idiomas_chamados)


def test_buscar_claims_respeita_idioma_explicito(monkeypatch):
    idiomas_chamados = []

    def _fake_buscar_pagina(cid, idioma):
        idiomas_chamados.append(idioma)
        return None

    monkeypatch.setattr(gp, "_buscar_pagina", _fake_buscar_pagina)
    buscar_claims("US6421675B1", idioma="de")

    assert idiomas_chamados and all(i == "de" for i in idiomas_chamados)
