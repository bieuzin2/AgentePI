from __future__ import annotations

import duckdb

import inpi.consulta as consulta
from inpi.validar_plataforma_nova import (
    amostrar_legado,
    amostrar_processos,
    amostrar_sigilo_com_procurador_conhecido,
    montar_relatorio,
)


def test_montar_relatorio_separa_recentes_de_antigos_e_calcula_taxas():
    resultados = [
        {"numero_inpi": "1", "recente": True, "sucesso": True, "indexado": True, "erro": None},
        {"numero_inpi": "2", "recente": True, "sucesso": False, "indexado": None, "erro": "500"},
        {"numero_inpi": "3", "recente": False, "sucesso": True, "indexado": True, "erro": None},
    ]
    r = montar_relatorio(resultados)

    assert r["total_amostrado"] == 3
    assert r["recentes"] == {"total": 2, "sucesso": 1, "indexado": 1,
                             "taxa_sucesso": 0.5, "taxa_indexado": 0.5}
    assert r["antigos"] == {"total": 1, "sucesso": 1, "indexado": 1,
                            "taxa_sucesso": 1.0, "taxa_indexado": 1.0}
    assert r["erros_exemplo"] == ["500"]


def test_montar_relatorio_com_grupo_vazio_nao_quebra():
    r = montar_relatorio([])
    assert r["recentes"]["total"] == 0
    assert r["recentes"]["taxa_sucesso"] is None


def test_amostrar_processos_separa_recentes_e_antigos(monkeypatch, tmp_path):
    banco = duckdb.connect(str(tmp_path / "fixture.duckdb"))
    banco.execute("""
      CREATE TABLE biblio (numero_inpi VARCHAR, data_deposito DATE)
    """)
    banco.execute("""
      CREATE TABLE ficha_extras (numero_inpi VARCHAR, cpc VARCHAR,
        escritorio_canonico VARCHAR, fonte VARCHAR, coletado_em VARCHAR)
    """)
    banco.execute("INSERT INTO biblio VALUES "
                  "('1', DATE '2026-08-20'), ('2', DATE '2020-01-01')")
    banco.execute("INSERT INTO ficha_extras VALUES "
                  "('1', NULL, 'clarke', 'pePI', '2026-08-25'), "
                  "('2', NULL, 'clarke', 'pePI', '2026-08-25')")
    monkeypatch.setattr(consulta, "con", lambda: banco)

    amostra = amostrar_processos("clarke", tamanho=10, dias_recentes=45)

    assert {a["numero_inpi"] for a in amostra} == {"1", "2"}
    recentes = {a["numero_inpi"] for a in amostra if a["recente"]}
    assert recentes == {"1"}


def test_amostrar_processos_exclui_formato_legado_pi(monkeypatch, tmp_path):
    banco = duckdb.connect(str(tmp_path / "fixture.duckdb"))
    banco.execute("CREATE TABLE biblio (numero_inpi VARCHAR, data_deposito DATE)")
    banco.execute("""
      CREATE TABLE ficha_extras (numero_inpi VARCHAR, cpc VARCHAR,
        escritorio_canonico VARCHAR, fonte VARCHAR, coletado_em VARCHAR)
    """)
    banco.execute("INSERT INTO biblio VALUES "
                  "('102022010731', DATE '2020-01-01'), ('PI9401632', DATE '2020-01-01')")
    banco.execute("INSERT INTO ficha_extras VALUES "
                  "('102022010731', NULL, 'clarke', 'pePI', '2026-08-25'), "
                  "('PI9401632', NULL, 'clarke', 'pePI', '2026-08-25')")
    monkeypatch.setattr(consulta, "con", lambda: banco)

    amostra = amostrar_processos("clarke", tamanho=10, dias_recentes=45)

    assert {a["numero_inpi"] for a in amostra} == {"102022010731"}


def test_amostrar_legado_traz_so_formato_pi(monkeypatch, tmp_path):
    banco = duckdb.connect(str(tmp_path / "fixture.duckdb"))
    banco.execute("""
      CREATE TABLE ficha_extras (numero_inpi VARCHAR, cpc VARCHAR,
        escritorio_canonico VARCHAR, fonte VARCHAR, coletado_em VARCHAR)
    """)
    banco.execute("INSERT INTO ficha_extras VALUES "
                  "('102022010731', NULL, 'clarke', 'pePI', '2026-08-25'), "
                  "('PI9401632', NULL, 'clarke', 'pePI', '2026-08-25'), "
                  "('PI8502923', NULL, 'clarke', 'pePI', '2026-08-25')")
    monkeypatch.setattr(consulta, "con", lambda: banco)

    amostra = amostrar_legado(tamanho=10)

    assert set(amostra) == {"PI9401632", "PI8502923"}


def test_amostrar_sigilo_com_procurador_conhecido_filtra_certo(monkeypatch, tmp_path):
    banco = duckdb.connect(str(tmp_path / "fixture.duckdb"))
    banco.execute("CREATE TABLE biblio (numero_inpi VARCHAR, sigilo DOUBLE)")
    banco.execute("""
      CREATE TABLE procuradores (numero_inpi VARCHAR, procurador VARCHAR,
        cgccpfprocurador VARCHAR)
    """)
    banco.execute("INSERT INTO biblio VALUES "
                  "('1', 1.0), ('2', 1.0), ('3', NULL), ('PI123', 1.0)")
    banco.execute("INSERT INTO procuradores VALUES "
                  # '1': sigilo, procurador vindo da coleta pePI (cgcc NULL) -- entra
                  "('1', 'CLARKE MODET', NULL), "
                  # '2': sigilo, mas procurador vindo do dump aberto (cgcc preenchido) -- fora
                  "('2', 'OUTRO ESCRITORIO', '12345678000100'), "
                  # '3': procurador conhecido mas NAO e sigilo -- fora
                  "('3', 'TERCEIRO', NULL), "
                  # 'PI123': sigilo + procurador sigilo, mas formato legado -- fora
                  "('PI123', 'QUARTO', NULL)")
    monkeypatch.setattr(consulta, "con", lambda: banco)

    amostra = amostrar_sigilo_com_procurador_conhecido(tamanho=10)

    assert amostra == [{"numero_inpi": "1", "procurador": "CLARKE MODET"}]
