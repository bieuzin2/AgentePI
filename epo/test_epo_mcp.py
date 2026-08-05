"""Testes do epo_mcp que rodam SEM credencial e SEM rede.

Cobrem o que quebra em silencio: o achatamento do JSON do EPO (que empacota texto
em {'$': ...} e alterna dict/lista para o mesmo campo) e as guardas de faixa.
O aceite contra a API ao vivo e outra coisa -- ver docs/aceite/A2.md.
"""

import pytest

from epo import epo_mcp as m


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


class _Resp:
    content = b"x"

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _Cli:
    def __init__(self, payload):
        self._p = payload

    def published_data(self, **kw):
        return _Resp(self._p)

    def register(self, **kw):
        return _Resp(self._p)


REGISTER_EP = {"ops:world-patent-data": {"ops:register-search": {
    "reg:register-documents": {"reg:register-document": {
        "reg:bibliographic-data": {
            "reg:designation-of-states": [
                {"reg:designation-pct": {"reg:regions": {"reg:country": [
                    {"$": "AT"}, {"$": "BE"}, {"$": "FR"}, {"$": "GB"}, {"$": "NL"},
                ]}}},
            ],
            # Formato real: o Register prefixa TUDO com 'reg:'. A versao sem prefixo
            # passava no teste e falhava contra a API -- foi assim que a mencao de
            # concessao voltava None em EP3088824, que tem B1 em 20181128.
            "reg:publication-reference": [
                {"reg:document-id": {"reg:country": {"$": "EP"},
                                     "reg:doc-number": {"$": "3088824"},
                                     "reg:kind": {"$": "A1"}, "reg:date": {"$": "20161102"}}},
                {"reg:document-id": {"reg:country": {"$": "EP"},
                                     "reg:doc-number": {"$": "3088824"},
                                     "reg:kind": {"$": "B1"}, "reg:date": {"$": "20181128"}}},
            ],
        },
        "reg:ep-patent-statuses": {"reg:ep-patent-status": [
            {"@change-date": "20191004", "@status-code": "7",
             "$": "No opposition filed within time limit"},
            {"@change-date": "20181026", "@status-code": "8",
             "$": "The patent has been granted"},
        ]},
    }}}}}


def test_register_extrai_estados_designados(monkeypatch):
    """O buraco do Acordo de Londres: em BE, FR, GB, NL a validacao nao gera
    publicacao nacional, entao nao ha membro INPADOC. O Register e a unica fonte
    que ao menos diz que esses estados foram designados."""
    _liga(monkeypatch, REGISTER_EP)
    r = m.epo_register("EP3088824")
    assert r["encontrado"] is True
    assert r["estados_designados"] == ["AT", "BE", "FR", "GB", "NL"]
    # a mencao de concessao e a publicacao do B1 -- dela corre o prazo do art. 65 EPC.
    # Conferido ao vivo: EP3088824 devolve 20181128, que e exatamente a coluna
    # 'concessao' do docketing da Tecnored.
    assert r["mencao_de_concessao"] == "20181128"
    assert r["situacao"] == "No opposition filed within time limit"
    assert r["situacao_em"] == "20191004", "vale a situacao mais recente"
    # o aviso tem que desmentir a leitura perigosa: designado != validado
    assert "NAO E VALIDACAO" in r["aviso"]


def test_register_recusa_o_que_nao_e_ep():
    r = m.epo_register("BR-102022010731-A2")
    assert r["erro"] is True


def test_register_404_nao_vira_falha_de_sistema(monkeypatch):
    class _Cli404:
        def register(self, **kw):
            raise Exception("404 Client Error: Not Found for url: ...")

    monkeypatch.setattr(m, "cliente", lambda: _Cli404())
    r = m.epo_register("EP9999999")
    assert r["encontrado"] is False
    assert r["estados_designados"] == []


def _liga(monkeypatch, payload):
    monkeypatch.setattr(m, "cliente", lambda: _Cli(payload))
    monkeypatch.setattr(m, "_loga_quota", lambda *a: None)


def test_texto_integral_extrai_descricao(monkeypatch):
    """Regressao: 'description' caia no else e voltava texto vazio, com
    disponivel=False. Vazio aqui e lido como 'o documento nao revela nada', que e
    exatamente a conclusao que o protocolo de citacao proibe."""
    _liga(monkeypatch, {"ops:world-patent-data": {"ftxt:fulltext-documents": {
        "ftxt:fulltext-document": {"description": {"p": [
            {"@num": "0001", "$": "Primeiro paragrafo."},
            {"@num": "0002", "$": "Segundo paragrafo."},
        ]}}}}})
    r = m.epo_texto_integral("EP1000000A1", secao="description")
    assert r["disponivel"] is True
    # paragrafo a paragrafo, nao '; ' -- a ancora tripla cita '[0034]'
    assert r["texto"] == "Primeiro paragrafo.\n\nSegundo paragrafo."


def test_texto_integral_extrai_resumo_preferindo_ingles(monkeypatch):
    """'abstract' vem do endpoint biblio, em outra arvore, e o mesmo documento
    traz varias linguas."""
    _liga(monkeypatch, {"ops:world-patent-data": {"exchange-documents": {
        "exchange-document": {"abstract": [
            {"@lang": "de", "p": {"$": "Eine Vorrichtung."}},
            {"@lang": "en", "p": {"$": "An apparatus for X."}},
        ]}}}})
    r = m.epo_texto_integral("EP1000000A1", secao="abstract")
    assert r["texto"] == "An apparatus for X."
    assert r["bruto_json"] is None


def test_texto_integral_resumo_sem_ingles_nao_volta_vazio(monkeypatch):
    """Texto em alemao e melhor que campo vazio lido como ausencia de revelacao."""
    _liga(monkeypatch, {"ops:world-patent-data": {"exchange-documents": {
        "exchange-document": {"abstract": {"@lang": "de", "p": {"$": "Eine Vorrichtung."}}}}}})
    assert m.epo_texto_integral("EP1000000A1", secao="abstract")["texto"] == "Eine Vorrichtung."


def test_quota_soma_os_dois_formatos_de_carimbo(tmp_path, monkeypatch):
    """Regressao de leitura: epo_mcp grava ISO 8601 e familia_epo grava epoch, no
    MESMO arquivo. Ler so um dos formatos subestima o consumo -- e subestimar cota
    e descobrir o teto no dia do prazo."""
    from datetime import datetime, timedelta, timezone

    agora = datetime.now(timezone.utc)
    log = tmp_path / "quota.log"
    log.write_text(
        f"{agora.isoformat()}\tbusca\t1000\n"
        f"{agora.timestamp():.0f}\tfamilia:102022010731\t2000\n"
        f"{(agora - timedelta(days=30)).isoformat()}\tbusca\t999999999\n"
        "linha corrompida\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(m, "QUOTA_LOG", log)
    r = m.epo_quota(dias=7)
    assert r["bytes"] == 3000, "os dois formatos contam; o de 30 dias atras nao"
    assert r["chamadas"] == 2
    assert r["linhas_ilegiveis"] == 1
    assert r["bytes_por_operacao"] == {"familia": 2000, "busca": 1000}
    assert r["alerta"] == ""


def test_quota_alerta_perto_do_teto(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    log = tmp_path / "quota.log"
    log.write_text(
        f"{datetime.now(timezone.utc).isoformat()}\tfamilia\t{int(3.6 * 1024**3)}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(m, "QUOTA_LOG", log)
    assert "ACIMA DE 80%" in m.epo_quota()["alerta"]


def test_cliente_falha_alto_sem_credencial(monkeypatch):
    monkeypatch.delenv("EPO_OPS_KEY", raising=False)
    monkeypatch.delenv("EPO_OPS_SECRET", raising=False)
    monkeypatch.setattr(m, "_client", None)
    with pytest.raises(RuntimeError, match="EPO_OPS_KEY"):
        m.cliente()
