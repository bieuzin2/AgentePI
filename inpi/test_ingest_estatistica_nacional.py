from __future__ import annotations

import csv

import duckdb

from inpi.ingest import _mescla_estatistica_nacional


def test_mescla_estatistica_nacional_cria_tabela_a_partir_do_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "estatistica-nacional.csv"
    campos = ["ano", "tipo_ativo", "sub_tipo", "tipo_patente", "via_entrada",
             "origem", "pais", "uf", "regiao", "campo_tecnologico", "decisao",
             "ano_decisao", "depositos", "concessoes", "n_decisoes",
             "n_vigentes", "coletado_em"]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerow({"ano": 2024, "tipo_ativo": "Patentes", "sub_tipo": "Patente de Invenção",
                   "tipo_patente": "Patente de Invenção", "via_entrada": "PCT",
                   "origem": "Residente", "pais": "Brasil", "uf": "Diversas UF",
                   "regiao": "Brasil", "campo_tecnologico": "Química",
                   "decisao": "Concessão", "ano_decisao": 2024, "depositos": 100,
                   "concessoes": 40, "n_decisoes": 40, "n_vigentes": 40,
                   "coletado_em": "2026-09-04"})

    import inpi.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "ESTATISTICA_NACIONAL", csv_path)

    con = duckdb.connect(":memory:")
    _mescla_estatistica_nacional(con)

    linhas = con.execute("SELECT ano, tipo_ativo, depositos FROM estatistica_nacional").fetchall()
    assert linhas == [(2024, "Patentes", 100)]


def test_mescla_estatistica_nacional_sem_csv_nao_cria_tabela(tmp_path, monkeypatch):
    import inpi.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "ESTATISTICA_NACIONAL", tmp_path / "nao-existe.csv")

    con = duckdb.connect(":memory:")
    _mescla_estatistica_nacional(con)

    tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert "estatistica_nacional" not in tabelas
