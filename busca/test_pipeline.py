from __future__ import annotations

from busca import pipeline
from inpi import familia_epo


def _inpi_busca_texto(termos, campo="ambos", limite=20, desde=None):
    return {"resultados": [{"numero_inpi": "A1", "titulo": "embalagem biodegradavel",
                            "data_publicacao": "2019-01-01", "data_deposito": "2018-01-01"}]}


def _inpi_busca_ipc(simbolo, limite=20, desde=None):
    return {"resultados": [{"numero_inpi": "B2", "titulo": "outro caso",
                            "data_deposito": "2017-01-01"}]}


def _epo_busca(cql, inicio=1, fim=25):
    return {"resultados": ["EP-1-A1"]}


def _epo_biblio(referencia):
    return {"documentos": [{"titulo": "embalagem biodegradavel EP",
                            "data_publicacao": "2019-06-01"}]}


def _epo_familia_inpadoc(referencia):
    # EP-1-A1 e BR-A1 sao a mesma familia -- deve deduplicar com o resultado do INPI.
    return {"membros": [{"referencia": "BR-A1"}]}


def _familia_a1(numero_br, cli=None):
    return {"membros": [{"referencia": "EP-1-A1"}]}


def _familia_b2(numero_br, cli=None):
    return {"erro": "nao encontrado", "membros": []}  # familia nao resolvida -- fica sozinho


def _familia(numero_br, cli=None):
    return _familia_a1(numero_br) if numero_br == "A1" else _familia_b2(numero_br)


def _openalex_buscar(termos, desde=None, limite=20):
    return {"resultados": [{"titulo": "artigo cientifico", "fonte": "openalex",
                            "data_publicacao": "2015-01-01", "autores": []}]}


def _liga(monkeypatch):
    monkeypatch.setattr(pipeline, "inpi_busca_texto", _inpi_busca_texto)
    monkeypatch.setattr(pipeline, "inpi_busca_ipc", _inpi_busca_ipc)
    monkeypatch.setattr(familia_epo, "familia", _familia)
    monkeypatch.setattr(pipeline.openalex, "buscar", _openalex_buscar)

    import epo.epo_mcp as epo_mod
    monkeypatch.setattr(epo_mod, "epo_busca", _epo_busca)
    monkeypatch.setattr(epo_mod, "epo_biblio", _epo_biblio)
    monkeypatch.setattr(epo_mod, "epo_familia_inpadoc", _epo_familia_inpadoc)


def test_deduplica_por_familia_inpadoc(monkeypatch):
    _liga(monkeypatch)
    d = pipeline.busca_anterioridade(["embalagem biodegradavel"], ipc=["B65D"])

    patentes = d["resultados_patentes"]
    # A1 (INPI) e EP-1-A1 (EPO) sao a mesma familia -> 1 grupo; B2 (IPC) e outro.
    assert len(patentes) == 2
    fundido = next(p for p in patentes if p["referencia"] in ("BR-A1", "EP-1-A1"))
    assert set(fundido["fontes"]) == {"inpi:texto", "epo:cql"}
    assert fundido["familia_resolvida"] is True

    isolado = next(p for p in patentes if p["referencia"] == "BR-B2")
    assert isolado["familia_resolvida"] is False

    assert d["resultados_npl"][0]["titulo"] == "artigo cientifico"
    assert d["estrategia"]["fontes_executadas"]["ppubs"]["executou"] is False
    assert "veredito" not in d["aviso"].lower() or "nao" in d["aviso"].lower()


def test_sem_conceitos_erro():
    assert pipeline.busca_anterioridade([]).get("erro") is True


def test_data_critica_marca_sem_decidir(monkeypatch):
    _liga(monkeypatch)
    d = pipeline.busca_anterioridade(["embalagem"], data_critica="2019-03-01")
    fundido = next(p for p in d["resultados_patentes"]
                   if p["referencia"] in ("BR-A1", "EP-1-A1"))
    assert fundido["anterior_a_data_critica"] is True  # 2019-01-01 < 2019-03-01
    npl = d["resultados_npl"][0]
    assert npl["anterior_a_data_critica"] is True


def test_data_critica_aceita_objeto_date(monkeypatch):
    """Regressao: fonte real pode devolver data como objeto date; comparar date < str
    levantava TypeError. Agora coage os dois lados a ISO-string."""
    from datetime import date

    _liga(monkeypatch)

    def _inpi_data_objeto(termos, campo="ambos", limite=20, desde=None):
        return {"resultados": [{"numero_inpi": "A1", "titulo": "x",
                                "data_publicacao": date(2019, 1, 1),
                                "data_deposito": date(2018, 1, 1)}]}

    monkeypatch.setattr(pipeline, "inpi_busca_texto", _inpi_data_objeto)
    d = pipeline.busca_anterioridade(["embalagem"], data_critica="2019-03-01")
    fundido = next(p for p in d["resultados_patentes"] if p["referencia"] == "BR-A1")
    assert fundido["anterior_a_data_critica"] is True  # 2019-01-01 < 2019-03-01, sem TypeError


def test_fonte_com_erro_nao_derruba_pipeline(monkeypatch):
    _liga(monkeypatch)

    def _quebra(*a, **k):
        raise RuntimeError("EPO fora do ar")

    import epo.epo_mcp as epo_mod
    monkeypatch.setattr(epo_mod, "epo_busca", _quebra)

    d = pipeline.busca_anterioridade(["embalagem"])
    assert d["estrategia"]["fontes_executadas"]["epo:cql"]["executou"] is False
    assert "EPO fora do ar" in d["estrategia"]["fontes_executadas"]["epo:cql"]["erro"]
