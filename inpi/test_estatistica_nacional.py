from __future__ import annotations

import duckdb

import inpi.consulta as consulta
from inpi.estatistica_nacional import inpi_estatistica_nacional


def _banco_fixture():
    con = duckdb.connect(":memory:")
    con.execute("""
      CREATE TABLE estatistica_nacional (
        ano INTEGER, tipo_ativo VARCHAR, sub_tipo VARCHAR, tipo_patente VARCHAR,
        via_entrada VARCHAR, origem VARCHAR, pais VARCHAR, uf VARCHAR,
        regiao VARCHAR, campo_tecnologico VARCHAR, decisao VARCHAR,
        ano_decisao INTEGER, depositos INTEGER, concessoes INTEGER,
        n_decisoes INTEGER, n_vigentes INTEGER, coletado_em VARCHAR
      )
    """)
    con.execute("""
      INSERT INTO estatistica_nacional VALUES
        (2023, 'Patentes', NULL, NULL, NULL, NULL, NULL, NULL, 'Sudeste',
         'Química', 'Concessão', 2023, 100, 40, 40, 40, '2026-09-04'),
        (2023, 'Patentes', NULL, NULL, NULL, NULL, NULL, NULL, 'Sudeste',
         'Mecânica', 'Concessão', 2023, 50, 20, 20, 20, '2026-09-04'),
        (2024, 'Marcas', NULL, NULL, NULL, NULL, NULL, NULL, 'Sul',
         NULL, 'Concessão', 2024, 200, 150, 150, 150, '2026-09-04')
    """)
    return con


def test_agrega_por_ano_sem_filtro(monkeypatch):
    monkeypatch.setattr(consulta, "con", _banco_fixture)
    monkeypatch.setattr(consulta, "_TABELAS", None)  # cache de schema e por-processo

    r = inpi_estatistica_nacional()

    assert r["por_ano"] == [
        {"ano": 2023, "depositos": 150, "concessoes": 60, "n_decisoes": 60, "n_vigentes": 60},
        {"ano": 2024, "depositos": 200, "concessoes": 150, "n_decisoes": 150, "n_vigentes": 150},
    ]
    assert r["total_depositos"] == 350


def test_filtra_por_tipo_ativo_e_campo_tecnologico(monkeypatch):
    monkeypatch.setattr(consulta, "con", _banco_fixture)
    monkeypatch.setattr(consulta, "_TABELAS", None)

    r = inpi_estatistica_nacional(tipo_ativo="Patentes", campo_tecnologico="Química")

    assert r["por_ano"] == [
        {"ano": 2023, "depositos": 100, "concessoes": 40, "n_decisoes": 40, "n_vigentes": 40},
    ]
    assert r["filtros"] == {"tipo_ativo": "Patentes", "campo_tecnologico": "Química"}


def test_tabela_ausente_devolve_erro_amigavel(monkeypatch):
    con_vazio = duckdb.connect(":memory:")
    monkeypatch.setattr(consulta, "con", lambda: con_vazio)
    monkeypatch.setattr(consulta, "_TABELAS", None)

    r = inpi_estatistica_nacional()

    assert r["erro"] is True
    assert "estatistica_nacional" in r["mensagem"]
