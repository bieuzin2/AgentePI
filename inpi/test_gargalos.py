"""Testes de inpi/gargalos.py -- estatistica pura sem banco, e smoke test
contra a base real (mesmo padrao de test_inpi_mcp.py: base local ja presente,
sem rede)."""

from datetime import date

from inpi import gargalos as g


def test_estatisticas_dias_ignora_marcos_ausentes():
    marcos = [
        {"dep": date(2020, 1, 1), "pub": date(2021, 1, 1)},
        {"dep": date(2020, 1, 1), "pub": None},
        {"dep": None, "pub": date(2021, 1, 1)},
    ]
    r = g._estatisticas_dias(marcos, "dep", "pub")
    assert r["casos"] == 1
    assert r["mediana_dias"] == 366


def test_estatisticas_dias_ignora_destino_anterior_a_origem():
    marcos = [{"dep": date(2020, 6, 1), "pub": date(2020, 1, 1)}]
    assert g._estatisticas_dias(marcos, "dep", "pub") is None


def test_estatisticas_dias_sem_casos_devolve_none():
    assert g._estatisticas_dias([], "dep", "pub") is None


def test_tempo_fases_real_traz_transicoes_coerentes():
    r = g.inpi_tempo_fases(ipc_prefix="A61K", desde="2015-01-01")
    assert r["criterio"]["processos_avaliados"] > 0
    assert r["deposito_para_publicacao"]["mediana_dias"] > 0
    # concessao so acontece depois de deposito -- mediana precisa ser maior que
    # a mediana isolada de deposito->publicacao
    assert (r["deposito_para_concessao"]["mediana_dias"]
            >= r["deposito_para_publicacao"]["mediana_dias"])


def test_tempo_fases_filtro_sem_resultado_falha_alto():
    r = g.inpi_tempo_fases(ipc_prefix="ZZZ999NAOEXISTE")
    assert r["erro"] is True


def test_backlog_soma_faixas_igual_a_pendentes():
    r = g.inpi_backlog(ipc_prefix="A61K")
    assert sum(r["por_tempo_desde_deposito"].values()) == r["pendentes"]


def test_pipeline_comparado_escritorio_inexistente_falha_alto():
    r = g.inpi_pipeline_comparado(procurador="ESCRITORIO INEXISTENTE XYZ 123")
    assert r["erro"] is True


def test_pipeline_comparado_traz_os_dois_lados():
    r = g.inpi_pipeline_comparado(procurador="Clarke Modet")
    c = r["comparativo"]["deposito_para_publicacao"]
    assert c["escritorio"]["casos"] > 0
    assert c["media_inpi"]["casos"] > c["escritorio"]["casos"]
