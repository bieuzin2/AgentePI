"""Testes do modulo de priorizacao da coleta incremental (sem rede)."""

from __future__ import annotations

import duckdb

import vigilancia.incremento_plataforma_nova as inc


def test_numeros_despacho_novo_sem_banco_anterior_devolve_vazio(monkeypatch, tmp_path):
    monkeypatch.setattr(inc, "BANCO_ANTERIOR", tmp_path / "nao-existe.duckdb")
    monkeypatch.setattr(inc, "BANCO_INPI", tmp_path / "inpi.duckdb")
    assert inc.numeros_despacho_novo() == []


def test_numeros_despacho_novo_identifica_processo_com_despacho_novo(monkeypatch, tmp_path):
    antigo_path = tmp_path / "inpi_anterior.duckdb"
    novo_path = tmp_path / "inpi.duckdb"

    con_a = duckdb.connect(str(antigo_path))
    con_a.execute("CREATE TABLE despachos (numero_inpi VARCHAR, codigo_despacho VARCHAR, data_rpi VARCHAR)")
    con_a.execute("INSERT INTO despachos VALUES ('P1', '1.1', '2026-08-01')")
    con_a.close()

    con_n = duckdb.connect(str(novo_path))
    con_n.execute("CREATE TABLE despachos (numero_inpi VARCHAR, codigo_despacho VARCHAR, data_rpi VARCHAR)")
    # P1: mesmo despacho de antes (sem mudanca) + despacho novo -> conta como mudou.
    # P2: so existia antes, sumiu (nao deve aparecer -- so novidade importa aqui).
    # P3: despacho totalmente novo.
    con_n.execute("""
        INSERT INTO despachos VALUES
            ('P1', '1.1', '2026-08-01'),
            ('P1', '2.1', '2026-08-29'),
            ('P3', '1.1', '2026-08-29')
    """)
    con_n.close()

    monkeypatch.setattr(inc, "BANCO_ANTERIOR", antigo_path)
    monkeypatch.setattr(inc, "BANCO_INPI", novo_path)

    resultado = inc.numeros_despacho_novo()

    assert sorted(resultado) == ["P1", "P3"]
