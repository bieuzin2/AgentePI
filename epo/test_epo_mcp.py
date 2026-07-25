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
        # Formato real: o nome fica em '<papel>-name'.'name', e cada parte aparece
        # duas vezes -- '@data-format' epodoc (com sufixo '[BR]') e original.
        "parties": {
            "applicants": {
                "applicant": [
                    {
                        "@sequence": "1",
                        "@data-format": "epodoc",
                        "applicant-name": {"name": {"$": "BRASKEM SA [BR]"}},
                    },
                    {
                        "@sequence": "1",
                        "@data-format": "original",
                        "applicant-name": {"name": {"$": "BRASKEM S.A."}},
                    },
                ]
            },
            "inventors": {
                # parte unica chega como dict, nao lista -- caso que costuma quebrar
                "inventor": {
                    "@data-format": "original",
                    "inventor-name": {"name": {"$": "SILVA, JOAO"}},
                }
            },
        },
        # IPC do EPO vem em largura fixa do padrao WIPO, com flags no fim.
        "classifications-ipcr": {
            "classification-ipcr": [
                {"text": {"$": "B65D  65/    46            A I"}},
                {"text": {"$": "C08L   5/    04            A I"}},
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
    # Regressao: o nome vive em 'applicant-name'.'name'. Ler p['name'] devolve
    # lista vazia sem erro -- o titular some do relatorio e ninguem percebe.
    assert r["titulares"] == ["BRASKEM S.A."], "prefere @data-format=original"
    assert r["inventores"] == ["SILVA, JOAO"]  # parte unica (dict) virou lista de 1
    assert r["ipc"] == ["B65D65/46", "C08L5/04"]  # padding de largura fixa removido
    assert r["data_publicacao"] == "20201215"


@pytest.mark.parametrize(
    "bruto,esperado",
    [
        ("B65D  65/    46            A I", "B65D65/46"),
        ("C08L  99/    00            A I", "C08L99/00"),
        ("A01N   1/    02", "A01N1/02"),
        ("texto que nao e ipc", "texto que nao e ipc"),
    ],
)
def test_normaliza_ipc(bruto, esperado):
    assert m._normaliza_ipc(bruto) == esperado


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


@pytest.mark.parametrize(
    "ref", ["BR-102022010731-A2", "BR102022010731A2", "BR.102022010731.A2", "br-102022010731-a2"]
)
def test_entrada_com_kind_vira_docdb(ref):
    """Regressao: 'BR102022010731A2' como Epodoc devolve 404 na API do EPO.
    Com kind conhecido a entrada tem que virar Docdb, que aceita o kind."""
    e = m._entrada(ref)
    assert isinstance(e, m.epo_ops.models.Docdb)
    assert (e.country_code, e.number, e.kind_code) == ("BR", "102022010731", "A2")
    assert e.as_api_input() == "(BR).(102022010731).(A2)"


def test_entrada_sem_kind_vira_epodoc_sem_kind():
    e = m._entrada("BR102022010731")
    assert isinstance(e, m.epo_ops.models.Epodoc)
    assert e.number == "BR102022010731"


def test_entrada_aceita_o_que_a_propria_busca_devolve():
    """epo_busca devolve 'PAIS-NUMERO-KIND'; colar isso em biblio/familia
    tem que funcionar sem o modelo precisar reformatar nada."""
    assert m._entrada("EP-1000000-A1") is not None


def test_entrada_recusa_lixo():
    with pytest.raises(ValueError):
        m._entrada("nao é uma referência")


def test_sem_resultado_reconhece_404():
    """Regressao: o EPO devolve 404 para busca vazia. Tratar como erro faz
    uma busca legitimamente sem resultado parecer falha de sistema."""
    assert m._sem_resultado(Exception("404 Client Error: Not Found for url: ...")) is True
    assert m._sem_resultado(Exception("500 Server Error")) is False


def test_cliente_falha_alto_sem_credencial(monkeypatch):
    monkeypatch.delenv("EPO_OPS_KEY", raising=False)
    monkeypatch.delenv("EPO_OPS_SECRET", raising=False)
    monkeypatch.setattr(m, "_client", None)
    with pytest.raises(RuntimeError, match="EPO_OPS_KEY"):
        m.cliente()
