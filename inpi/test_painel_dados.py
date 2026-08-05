"""Testes de inpi/painel_dados.py -- dados sinteticos, sem tocar o banco real.

Cobre as 2 secoes novas do dashboard (Fase 2, plano 4.3): alertas da semana
(le do duckdb da vigilancia) e anuidades 90 dias (recorte do prazos_12m que
panorama() ja projeta).
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from inpi import painel_dados as pd


def test_alertas_semana_sem_banco_retorna_lista_vazia(tmp_path):
    assert pd._alertas_semana(tmp_path / "nao_existe.duckdb") == []


def test_alertas_semana_le_do_duckdb_mais_recente_primeiro(tmp_path):
    banco = tmp_path / "alertas.duckdb"
    con = duckdb.connect(str(banco))
    con.execute("""CREATE TABLE alertas (
        id BIGINT, tipo VARCHAR, severidade VARCHAR, processo VARCHAR,
        titular VARCHAR, mensagem VARCHAR, data VARCHAR, fonte VARCHAR,
        data_corte VARCHAR, criado_em VARCHAR, visto BOOLEAN DEFAULT FALSE
    )""")
    con.execute("INSERT INTO alertas VALUES "
                "(1,'despacho_novo','media','BR102022010731','x','msg1',"
                "'2026-08-01','fonte','2026-08-01 (RPI x)','2026-08-01T10:00:00',FALSE)")
    con.execute("INSERT INTO alertas VALUES "
                "(2,'anulacao','alta','PI0803071','y','msg2',"
                "'2026-08-02','fonte','2026-08-02 (RPI y)','2026-08-02T10:00:00',FALSE)")
    con.close()

    r = pd._alertas_semana(banco)
    assert len(r) == 2
    assert r[0]["processo"] == "PI0803071"  # mais recente primeiro
    assert r[0]["severidade"] == "alta"


def test_anuidades_90d_filtra_tipo_e_janela():
    ref = date(2026, 8, 5)
    prazos = {"lista": [
        {"tipo": "anuidade", "prazo": "2026-09-01", "numero_inpi": "A"},
        {"tipo": "anuidade", "prazo": "2027-01-01", "numero_inpi": "B"},  # fora dos 90d
        {"tipo": "exame", "prazo": "2026-09-01", "numero_inpi": "C"},  # tipo errado
        {"tipo": "anuidade", "prazo": "2026-08-10", "numero_inpi": "D"},
    ]}
    r = pd._anuidades_90d(prazos, ref)
    assert [p["numero_inpi"] for p in r] == ["D", "A"]  # ordenado por prazo


def test_montar_inclui_placeholders_de_tarefas_e_landscape(tmp_path, monkeypatch):
    def _panorama_stub(procurador, hoje=None):
        return {
            "cobertura": {}, "total_casos": 0, "situacao": {},
            "prazos_12m": {"lista": []},
        }

    monkeypatch.setattr(pd.pc, "panorama", _panorama_stub)
    d = pd.montar("Clarke Modet", hoje="2026-08-05",
                   banco_alertas=tmp_path / "sem_banco.duckdb")
    assert d["alertas_semana"] == []
    assert d["anuidades_90d"] == []
    assert d["tarefas"]["lista"] == []
    assert "Fase 6" in d["tarefas"]["nota"]
    assert "Fase 5" in d["landscape"]["nota"]
