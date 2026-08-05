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
from inpi import tarefas as tf


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


def test_montar_inclui_placeholder_de_landscape(tmp_path, monkeypatch):
    def _panorama_stub(procurador, hoje=None):
        return {
            "cobertura": {}, "total_casos": 0, "situacao": {},
            "prazos_12m": {"lista": []},
        }

    monkeypatch.setattr(pd.pc, "panorama", _panorama_stub)
    monkeypatch.setattr(tf, "BANCO", tmp_path / "sem_banco.duckdb")
    d = pd.montar("Clarke Modet", hoje="2026-08-05",
                   banco_alertas=tmp_path / "sem_banco_alertas.duckdb")
    assert d["alertas_semana"] == []
    assert d["anuidades_90d"] == []
    assert d["tarefas"]["lista"] == []
    assert d["tarefas"]["vencendo_7d"] == []
    assert "Fase 5" in d["landscape"]["nota"]


def test_montar_conecta_tarefas_abertas_e_alerta_de_vencimento(tmp_path, monkeypatch):
    """Dados sinteticos: uma tarefa vencendo em 7 dias, outra fora da janela."""
    def _panorama_stub(procurador, hoje=None):
        return {
            "cobertura": {}, "total_casos": 0, "situacao": {},
            "prazos_12m": {"lista": []},
        }

    monkeypatch.setattr(pd.pc, "panorama", _panorama_stub)
    monkeypatch.setattr(tf, "BANCO", tmp_path / "carteira.duckdb")
    tf.tarefa_criar("responder oficio", processo="BR1", prazo_interno="2026-08-10")
    tf.tarefa_criar("revisar contrato", processo="BR2", prazo_interno="2027-01-01")

    d = pd.montar("Clarke Modet", hoje="2026-08-05",
                   banco_alertas=tmp_path / "sem_banco_alertas.duckdb")
    assert len(d["tarefas"]["lista"]) == 2
    assert [t["processo"] for t in d["tarefas"]["vencendo_7d"]] == ["BR1"]
