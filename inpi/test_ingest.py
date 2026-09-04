# inpi/test_ingest.py (criar se nao existir)
"""Testes dos mesclas de referencia estatica de inpi/ingest.py (sem rede,
sem baixar dump -- so a logica de merge do CSV de referencia)."""

from __future__ import annotations

import duckdb

from inpi import ingest


def test_mescla_ipc_campo_tecnologico(monkeypatch, tmp_path):
    csv = tmp_path / "ipc-campo-tecnologico.csv"
    csv.write_text(
        "ipc_subclasse,campo_tecnologico\nA61K,Farmacêutica\nC08L,Polímeros\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ingest, "IPC_CAMPO_TECNOLOGICO", csv)

    con = duckdb.connect()
    ingest._mescla_ipc_campo_tecnologico(con)

    linhas = con.execute(
        "SELECT ipc_subclasse, campo_tecnologico FROM ipc_campo_tecnologico ORDER BY 1"
    ).fetchall()
    assert linhas == [("A61K", "Farmacêutica"), ("C08L", "Polímeros")]


def test_mescla_ipc_campo_tecnologico_sem_csv_nao_cria_tabela(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest, "IPC_CAMPO_TECNOLOGICO", tmp_path / "nao-existe.csv")
    con = duckdb.connect()
    ingest._mescla_ipc_campo_tecnologico(con)
    tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert "ipc_campo_tecnologico" not in tabelas
