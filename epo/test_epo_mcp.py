"""Testes do epo_mcp que rodam SEM credencial e SEM rede.

Cobrem o que quebra em silencio: o achatamento do JSON do EPO (que empacota texto
em {'$': ...} e alterna dict/lista para o mesmo campo) e as guardas de faixa.
O aceite contra a API ao vivo e outra coisa -- ver docs/aceite/A2.md.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import epo_mcp as m


# Formato real do EPO OPS: '$' para texto, '@' para atributo, campo repetido
# vira lista e campo unico vira dict.
EXCHANGE_BR = {
    "@country": "BR",
    "bibliographic-data": {
        "publication-reference": {
            "document-id": [
                {
                    "@document-id-type": "docdb",
                    "country": {"$": "BR"},
                    "doc-number": {"$": "102019000000"},
                    "kind": {"$": "A2"},
                    "date": {"$": "20201215"},
                }
            ]
        },
        "invention-title": [
            {"@lang": "en", "$": "Biodegradable packaging"},
            {"@lang": "pt", "$": "Embalagem biodegradavel"},
        ],
        "parties": {
            "applicants": {
                # campo unico chega como dict, nao lista -- caso que costuma quebrar
                "applicant": {"name": {"$": "BRASKEM S.A."}}
            }
        },
        "classifications-ipcr": {
            "classification-ipcr": [
                {"text": {"$": "B65D 65/46"}},
                {"text": {"$": "C08J 5/18"}},
            ]
        },
    },
}


def test_texto_achata_as_tres_formas():
    assert m._texto({"$": "abc"}) == "abc"
    assert m._texto("abc") == "abc"
    assert m._texto([{"$": "a"}, {"$": "b"}]) == "a; b"
    assert m._texto(None) == ""


def test_lista_normaliza_dict_unico():
    assert m._lista({"a": 1}) == [{"a": 1}]
    assert m._lista([1, 2]) == [1, 2]
    assert m._lista(None) == []


def test_ref_monta_identificador_legivel():
    doc = EXCHANGE_BR["bibliographic-data"]["publication-reference"]["document-id"]
    assert m._ref(doc) == "BR-102019000000-A2"


def test_resumo_extrai_campos_de_triagem():
    r = m._resumo_documento(EXCHANGE_BR)
    assert r["referencia"] == "BR-102019000000-A2"
    assert r["pais"] == "BR"
    assert r["titulo"] == "Biodegradable packaging"
    assert r["titulos_por_idioma"]["pt"] == "Embalagem biodegradavel"
    assert r["titulares"] == ["BRASKEM S.A."]  # dict unico virou lista de 1
    assert r["ipc"] == ["B65D 65/46", "C08J 5/18"]
    assert r["data_publicacao"] == "20201215"


def test_resumo_nao_quebra_com_documento_vazio():
    r = m._resumo_documento({})
    assert r["referencia"] == "" and r["titulares"] == []


def test_busca_recusa_acima_do_teto_do_epo():
    # Precisa falhar ANTES de tocar a rede: nao ha credencial neste ambiente.
    r = m.epo_busca(cql='ti="teste"', inicio=1, fim=2001)
    assert r["erro"] is True and "2000" in r["mensagem"]


def test_busca_recusa_faixa_invertida():
    assert m.epo_busca(cql='ti="teste"', inicio=50, fim=10)["erro"] is True


def test_texto_integral_recusa_secao_desconhecida():
    r = m.epo_texto_integral("EP1000000A1", secao="figuras")
    assert r["erro"] is True


def test_entrada_docdb_exige_tres_partes():
    with pytest.raises(ValueError):
        m._entrada("BR102019000000A2", "docdb")


def test_cliente_falha_alto_sem_credencial(monkeypatch):
    monkeypatch.delenv("EPO_OPS_KEY", raising=False)
    monkeypatch.delenv("EPO_OPS_SECRET", raising=False)
    monkeypatch.setattr(m, "_client", None)
    with pytest.raises(RuntimeError, match="EPO_OPS_KEY"):
        m.cliente()
