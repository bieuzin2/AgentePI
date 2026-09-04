"""Testes de inpi/mercado_fila.py contra um arquivo DuckDB proprio em
tmp_path -- sem rede, sem tocar inpi.duckdb nem fila_mercado.duckdb real."""

from __future__ import annotations

import duckdb

import inpi.mercado_fila as fila


def test_proximo_lote_prioriza_concorrente_antes_de_nacional(monkeypatch, tmp_path):
    banco = tmp_path / "fila_mercado.duckdb"
    monkeypatch.setattr(fila, "BANCO_FILA", banco)

    con = fila._con()
    con.execute(
        "INSERT INTO fila_mercado VALUES "
        "('N1', 'nacional', 'pendente', 0, '2026-09-01'), "
        "('C1', 'concorrente', 'pendente', 0, '2026-09-01'), "
        "('C2', 'concorrente', 'pendente', 0, '2026-09-01')"
    )
    con.close()

    lote = fila.proximo_lote(2)

    assert lote == ["C1", "C2"]


def test_marcar_atualiza_status(monkeypatch, tmp_path):
    banco = tmp_path / "fila_mercado.duckdb"
    monkeypatch.setattr(fila, "BANCO_FILA", banco)

    con = fila._con()
    con.execute(
        "INSERT INTO fila_mercado VALUES "
        "('N1', 'nacional', 'pendente', 0, '2026-09-01')"
    )
    con.close()

    fila.marcar(["N1"], "coletado")

    con = fila._con()
    status = con.execute(
        "SELECT status FROM fila_mercado WHERE numero_inpi = 'N1'"
    ).fetchone()[0]
    con.close()
    assert status == "coletado"


def test_proximo_lote_ignora_ja_coletados(monkeypatch, tmp_path):
    banco = tmp_path / "fila_mercado.duckdb"
    monkeypatch.setattr(fila, "BANCO_FILA", banco)

    con = fila._con()
    con.execute(
        "INSERT INTO fila_mercado VALUES "
        "('N1', 'nacional', 'coletado', 1, '2026-09-01'), "
        "('N2', 'nacional', 'pendente', 0, '2026-09-01')"
    )
    con.close()

    assert fila.proximo_lote(10) == ["N2"]
