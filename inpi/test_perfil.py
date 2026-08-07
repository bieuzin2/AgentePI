"""Testes de inpi/perfil.py -- agregacoes mockadas (sem DB/rede)."""

from unittest.mock import patch

import inpi.perfil as pf


def _patch(chaves, por_ano, total=None, foco=None, escr=None):
    soma = sum(r["depositos"] for r in por_ano)
    return patch.multiple(
        pf,
        chaves_de=lambda nome: chaves,
        resolver=lambda chave: {"nivel": "automatica", "chave": chave},
        relacionados=lambda chave: [],
        _por_ano=lambda chave: por_ano,
        _total_processos=lambda chave: total if total is not None else soma,
        _foco_tecnologico=lambda chave, n: foco or [],
        _escritorios=lambda chave, n, desde_ano=None: escr or [],
    )


def test_titular_inexistente():
    with _patch(chaves=[], por_ano=[]):
        r = pf.inpi_perfil_titular("Fantasma")
    assert r["encontrado"] is False


def test_total_reconcilia_com_sem_data_e_nao_cruza_abaixo_do_limiar():
    chaves = [{"chave": "ACME", "processos": 35, "exemplo": "ACME LTDA"}]
    por_ano = [{"ano": 2020, "depositos": 10}, {"ano": 2021, "depositos": 20}]
    # total 35, mas so 30 tem data de deposito -> 5 sem data
    with _patch(chaves, por_ano, total=35), \
         patch.object(pf, "_cruzar_bigquery") as cruz:
        r = pf.inpi_perfil_titular("Acme")
    assert r["total_processos_br"] == 35
    assert r["com_data_de_deposito"] == 30
    assert r["sem_data_de_deposito"] == 5
    assert r["evolucao_por_ano"] == por_ano
    cruz.assert_not_called()  # 35 < 200
    assert "cruzamento_bigquery" not in r


def test_cruza_acima_do_limiar():
    chaves = [{"chave": "BIG", "processos": 500, "exemplo": "BIG CORP"}]
    por_ano = [{"ano": 2020, "depositos": 500}]
    with _patch(chaves, por_ano), \
         patch.object(pf, "_cruzar_bigquery",
                      return_value={"contagem_br_bigquery": 480}) as cruz:
        r = pf.inpi_perfil_titular("Big")
    cruz.assert_called_once()
    # passa o nome-exemplo da chave para o BigQuery, nao o texto digitado
    assert cruz.call_args[0][0] == "BIG CORP"
    assert r["cruzamento_bigquery"]["contagem_br_bigquery"] == 480


def test_cruzamento_indisponivel_nao_derruba():
    r = pf._cruzar_bigquery("Nome Qualquer", 300)
    # sem ADC/landscape no ambiente de teste -> nota, nunca excecao
    assert r["contagem_br_inpi"] == 300
    assert r["contagem_br_bigquery"] is None or isinstance(
        r["contagem_br_bigquery"], int)
