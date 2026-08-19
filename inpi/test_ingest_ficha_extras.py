"""Regressao: merge de ficha-extras.csv na tabela ficha_extras.

Ao contrario de procuradores-sigilo.csv, nao ha tabela oficial equivalente --
ficha_extras e criada direto do CSV curado, so descartando numero_inpi que nao
existe em biblio. Ver _mescla_ficha_extras em inpi/ingest.py.
"""

from __future__ import annotations

import duckdb

from inpi import ingest as m


def _banco_minimo():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE biblio (codigo_interno INTEGER, numero_inpi VARCHAR)")
    con.execute("INSERT INTO biblio VALUES (1, '102020000001')")
    return con


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
