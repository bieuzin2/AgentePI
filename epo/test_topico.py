"""Testes de epo/topico.py -- montagem de CQL, agregacao, validacao. Sem rede."""

from unittest.mock import MagicMock, patch

from epo import topico as tp


def test_monta_cql_so_termo():
    assert tp._monta_cql("covid", None, None, None) == "ta=(covid)"


def test_monta_cql_com_pais():
    assert tp._monta_cql("covid", "np", None, None) == "ta=(covid) and pn=NP"


def test_monta_cql_com_datas():
    assert tp._monta_cql("covid", None, "2020-01-01", "2021-06-30") == (
        'ta=(covid) and pd within "20200101 20210630"'
    )


def test_termos_vazios_recusa():
    r = tp.epo_panorama_topico("   ")
    assert r["erro"] is True


def test_amostra_fora_da_faixa_e_grampeada(monkeypatch):
    client = MagicMock()
    client.published_data_search.return_value.json.return_value = {
        "ops:world-patent-data": {"ops:biblio-search": {"@total-result-count": "0"}}
    }
    client.published_data_search.return_value.content = b"{}"
    with patch.object(tp, "cliente", return_value=client), \
         patch.object(tp, "_loga_quota"):
        tp.epo_panorama_topico("covid", amostra=99999)
    assert client.published_data_search.call_args.kwargs["range_end"] == tp.AMOSTRA_MAXIMA


def test_documentos_acha_em_qualquer_profundidade():
    corpo = {
        "ops:biblio-search": {
            "@total-result-count": "2",
            "ops:search-result": {
                "exchange-documents": {
                    "exchange-document": [
                        {"@country": "NP", "bibliographic-data": {}},
                        {"@country": "BR", "bibliographic-data": {}},
                    ]
                }
            },
        }
    }
    docs = tp._documentos(corpo)
    assert len(docs) == 2
    assert {d["@country"] for d in docs} == {"NP", "BR"}


def test_agrega_top_ipc_titulares_pais_ano():
    docs = [
        {"ipc": ["A61K31/00", "A61P31/00"], "titulares": ["ACME"], "pais": "NP",
         "data_publicacao": "20200601"},
        {"ipc": ["A61K31/00"], "titulares": ["ACME", "OUTRA"], "pais": "NP",
         "data_publicacao": "20210101"},
        {"ipc": [], "titulares": [], "pais": "BR", "data_publicacao": ""},
    ]
    agg = tp._agrega(docs)
    assert agg["top_ipc_subclasses"][0] == {"chave": "A61K", "documentos": 2}
    assert agg["titulares_distintos"] == 2
    assert agg["distribuicao_por_pais"] == [
        {"chave": "NP", "documentos": 2}, {"chave": "BR", "documentos": 1}
    ]
    assert agg["distribuicao_por_ano"] == [
        {"ano": "2020", "documentos": 1}, {"ano": "2021", "documentos": 1}
    ]


def test_nota_amostra_so_quando_total_maior_que_amostra():
    client = MagicMock()
    client.published_data_search.return_value.json.return_value = {
        "ops:world-patent-data": {
            "ops:biblio-search": {
                "@total-result-count": "3",
                "ops:search-result": {
                    "exchange-documents": {
                        "exchange-document": [
                            {"@country": "NP", "bibliographic-data": {}},
                        ]
                    }
                },
            }
        }
    }
    client.published_data_search.return_value.content = b"{}"
    with patch.object(tp, "cliente", return_value=client), \
         patch.object(tp, "_loga_quota"):
        r = tp.epo_panorama_topico("covid", amostra=1)
    assert r["total"] == 3
    assert "nota_amostra" in r


def test_sem_resultado_vira_resposta_vazia_nao_erro():
    client = MagicMock()
    client.published_data_search.side_effect = Exception("404 Client Error")
    with patch.object(tp, "cliente", return_value=client):
        r = tp.epo_panorama_topico("termo inexistente")
    assert r["total"] == 0 and r["top_titulares"] == []
