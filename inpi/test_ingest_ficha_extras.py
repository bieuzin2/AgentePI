"""Regressao: merge de ficha-extras.csv na tabela ficha_extras.

Ao contrario de procuradores-sigilo.csv, nao ha tabela oficial equivalente --
ficha_extras e criada direto do CSV curado, so descartando numero_inpi que nao
existe em biblio. Ver _mescla_ficha_extras em inpi/ingest.py.
"""

from __future__ import annotations

import csv

import duckdb

from inpi import ingest as m


def _banco_minimo():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE biblio (codigo_interno INTEGER, numero_inpi VARCHAR)")
    con.execute("INSERT INTO biblio VALUES (1, '102020000001')")
    return con


_CABECALHO = ["numero_inpi", "cpc", "peticoes_json", "anuidades_json",
              "link_documento", "escritorio_canonico", "fonte", "coletado_em"]


def _escreve_csv(caminho, linhas):
    with caminho.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(_CABECALHO)
        w.writerows(linhas)


def test_cria_tabela_a_partir_do_csv_curado(tmp_path, monkeypatch):
    csv = tmp_path / "ficha-extras.csv"
    csv.write_text(
        "numero_inpi,cpc,peticoes_json,anuidades_json,link_documento,"
        "escritorio_canonico,fonte,coletado_em\n"
        '102020000001,A01B 13/14,[],[],,CLARKE MODET,pePI,2026-08-11\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(m, "FICHA_EXTRAS", csv)
    con = _banco_minimo()

    m._mescla_ficha_extras(con)

    r = con.execute("SELECT cpc FROM ficha_extras WHERE numero_inpi = '102020000001'").fetchall()
    assert r == [("A01B 13/14",)]


def test_recoleta_mais_nova_vence_a_antiga(tmp_path, monkeypatch):
    """C1: registrar(atualizar=True) APENDA a recoleta no CSV append-only --
    aqui fica so a linha de coletado_em mais recente por numero_inpi."""
    csv_path = tmp_path / "ficha-extras.csv"
    _escreve_csv(csv_path, [
        ["102020000001", "A01B 13/14", "[]", "[]", "", "CLARKE MODET", "pePI", "2026-08-11"],
        ["102020000001", "C07D 1/00", "[]", "[]", "", "CLARKE MODET", "plataforma nova",
         "2026-09-04"],
    ])
    monkeypatch.setattr(m, "FICHA_EXTRAS", csv_path)
    con = _banco_minimo()

    m._mescla_ficha_extras(con)

    r = con.execute("SELECT cpc, coletado_em FROM ficha_extras").fetchall()
    assert r == [("C07D 1/00", "2026-09-04")]


def test_descarta_numero_inpi_que_nao_existe_em_biblio(tmp_path, monkeypatch):
    csv = tmp_path / "ficha-extras.csv"
    csv.write_text(
        "numero_inpi,cpc,peticoes_json,anuidades_json,link_documento,"
        "escritorio_canonico,fonte,coletado_em\n"
        '999999999999,A01B 13/14,[],[],,CLARKE MODET,pePI,2026-08-11\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(m, "FICHA_EXTRAS", csv)
    con = _banco_minimo()

    m._mescla_ficha_extras(con)

    n = con.execute("SELECT count(*) FROM ficha_extras").fetchone()[0]
    assert n == 0


def test_sem_csv_curado_nao_cria_tabela(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "FICHA_EXTRAS", tmp_path / "nao-existe.csv")
    con = _banco_minimo()

    m._mescla_ficha_extras(con)

    tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert "ficha_extras" not in tabelas


def test_expande_peticoes_e_anuidades_vetorizado(tmp_path, monkeypatch):
    # Regressao do bug de performance: a versao anterior fazia json.loads() +
    # executemany() linha a linha em Python -- 6h+ num ingest real de ~1,5M
    # peticoes/1,4M anuidades. Esta versao usa UNNEST(from_json(...)) do DuckDB.
    # Cobre tambem o campo 'gru' (Guia de Recolhimento da Uniao), que e o motivo
    # de existir a tabela ficha_anuidades.
    peticoes_json = ('[{"codigo":"206","descricao":"peticao x","banco":"BB",'
                      '"valor":"100","protocolo":"P1","data_protocolo":"2020-01-01"}]')
    anuidades_json = ('[{"numero":"3a","status":"paga","gru":"0000921007978251",'
                       '"valor":"250.00","data_pagamento":"2020-02-01"}]')
    csv_path = tmp_path / "ficha-extras.csv"
    _escreve_csv(csv_path, [
        ["102020000001", "A01B 13/14", peticoes_json, anuidades_json, "",
         "CLARKE MODET", "pePI", "2026-08-11"],
    ])
    monkeypatch.setattr(m, "FICHA_EXTRAS", csv_path)
    con = _banco_minimo()

    m._mescla_ficha_extras(con)

    pet = con.execute("SELECT numero_inpi, codigo, banco FROM ficha_peticoes").fetchall()
    assert pet == [("102020000001", "206", "BB")]
    anu = con.execute(
        "SELECT numero_inpi, numero, gru, valor FROM ficha_anuidades"
    ).fetchall()
    assert anu == [("102020000001", "3a", "0000921007978251", "250.00")]


def test_json_malformado_e_descartado_sem_derrubar_a_query(tmp_path, monkeypatch):
    # from_json() lanca excecao e derruba a query inteira se UMA linha for JSON
    # invalido -- json_valid() precisa filtrar ANTES. Dado de coleta externa,
    # nao confiavel 100%: uma linha quebrada nao pode sumir com as outras.
    boa = '[{"codigo":"1","descricao":"a","banco":"b","valor":"1","protocolo":"p","data_protocolo":"d"}]'
    csv_path = tmp_path / "ficha-extras.csv"
    _escreve_csv(csv_path, [
        ["102020000001", "", boa, "[]", "", "CLARKE MODET", "pePI", "2026-08-11"],
        ["102020000002", "", "[{codigo sem aspas}]", "[]", "", "CLARKE MODET",
         "pePI", "2026-08-11"],
    ])
    con = _banco_minimo()
    con.execute("INSERT INTO biblio VALUES (2, '102020000002')")
    monkeypatch.setattr(m, "FICHA_EXTRAS", csv_path)

    m._mescla_ficha_extras(con)  # nao pode levantar

    pet = con.execute("SELECT numero_inpi FROM ficha_peticoes").fetchall()
    assert pet == [("102020000001",)]
