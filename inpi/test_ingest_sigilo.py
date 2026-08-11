"""Regressao: merge de procuradores-sigilo.csv na tabela procuradores.

Preenche APENAS numero_inpi sem procurador oficial; nunca duplica quando o dump
ja trouxe o procurador de verdade (auto-cura na publicacao). Ver
_mescla_procuradores_sigilo em inpi/ingest.py.
"""

from __future__ import annotations

import duckdb
import pytest

from inpi import ingest as m


def _banco_minimo():
    con = duckdb.connect(":memory:")
    con.execute("""
        CREATE TABLE biblio (codigo_interno INTEGER, numero_inpi VARCHAR)
    """)
    con.execute("""
        INSERT INTO biblio VALUES
          (1, '102020000001'),  -- sigiloso, sem procurador oficial
          (2, '102020000002')   -- ja tem procurador oficial (publicado)
    """)
    con.execute("""
        CREATE TABLE procuradores (
            codigo_interno INTEGER, numero_inpi VARCHAR, procurador VARCHAR,
            cgccpfprocurador VARCHAR, tipopessoaprocurador VARCHAR,
            data_inicio_procurador DATE
        )
    """)
    con.execute("""
        INSERT INTO procuradores VALUES
          (2, '102020000002', 'OUTRO ESCRITORIO', '11111111000100',
           'Pessoa Jurídica', '2020-01-01')
    """)
    return con


def test_preenche_numero_inpi_sem_procurador(tmp_path, monkeypatch):
    csv = tmp_path / "procuradores-sigilo.csv"
    csv.write_text(
        "numero_inpi,procurador,escritorio_canonico,fonte,coletado_em,observacao\n"
        "102020000001,CLARKE MODET,CLARKE MODET,pePI,2026-08-11,busca por procurador\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(m, "PROCURADORES_SIGILO", csv)
    con = _banco_minimo()

    m._mescla_procuradores_sigilo(con)

    r = con.execute(
        "SELECT codigo_interno, procurador FROM procuradores WHERE numero_inpi = '102020000001'"
    ).fetchall()
    assert r == [(1, "CLARKE MODET")]


def test_ignora_numero_inpi_que_ja_tem_procurador_oficial(tmp_path, monkeypatch):
    csv = tmp_path / "procuradores-sigilo.csv"
    csv.write_text(
        "numero_inpi,procurador,escritorio_canonico,fonte,coletado_em,observacao\n"
        "102020000002,CLARKE MODET,CLARKE MODET,pePI,2026-08-11,dado obsoleto\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(m, "PROCURADORES_SIGILO", csv)
    con = _banco_minimo()

    m._mescla_procuradores_sigilo(con)

    r = con.execute(
        "SELECT procurador FROM procuradores WHERE numero_inpi = '102020000002'"
    ).fetchall()
    assert r == [("OUTRO ESCRITORIO",)]


def test_csv_escrito_por_registrar_e_lido_pelo_merge(tmp_path, monkeypatch):
    """Integra coleta_sigilo.registrar() com o merge do ingest.

    Pegou uma regressao real: csv.DictWriter grava linha terminada em '\\r\\n'
    por padrao, enquanto o cabecalho do arquivo (criado a mao) terminava em
    '\\n' -- terminador misto derrubava o sniffer de CSV do DuckDB com um
    arquivo de so 2 linhas (Invalid Input Error: nao foi possivel detectar o
    dialeto). Testes que escrevem o CSV a mao (com terminador uniforme) nunca
    exercitam esse caminho.
    """
    from inpi import coleta_sigilo as coleta

    csv = tmp_path / "procuradores-sigilo.csv"
    con = _banco_minimo()
    monkeypatch.setattr(coleta, "CSV_SIGILO", csv)
    monkeypatch.setattr(coleta, "con", lambda: con)
    coleta.registrar("102020000001", "CLARKE MODET", "CLARKE MODET", "pePI", "2026-08-11")

    monkeypatch.setattr(m, "PROCURADORES_SIGILO", csv)
    m._mescla_procuradores_sigilo(con)

    r = con.execute(
        "SELECT procurador FROM procuradores WHERE numero_inpi = '102020000001'"
    ).fetchall()
    assert r == [("CLARKE MODET",)]


def test_sem_csv_curado_nao_faz_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "PROCURADORES_SIGILO", tmp_path / "nao-existe.csv")
    con = _banco_minimo()

    m._mescla_procuradores_sigilo(con)

    n = con.execute("SELECT count(*) FROM procuradores").fetchone()[0]
    assert n == 1
