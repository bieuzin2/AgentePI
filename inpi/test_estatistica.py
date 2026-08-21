"""inpi_estatistica: motor de agregacao com guarda-corpos. Testa contra banco em
memoria (padrao de test_anuidades_pagas.py) -- nao depende da coleta real."""

from __future__ import annotations

import duckdb

from inpi import estatistica as m


def _con_fake(monkeypatch):
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE procuradores (numero_inpi VARCHAR, procurador VARCHAR)")
    con.execute("CREATE TABLE escritorios (original VARCHAR, chave VARCHAR)")
    con.execute("CREATE TABLE ficha_extras (numero_inpi VARCHAR)")
    con.execute("CREATE TABLE ficha_anuidades (numero_inpi VARCHAR, numero VARCHAR, "
                "status VARCHAR, gru VARCHAR, valor VARCHAR, data_pagamento VARCHAR)")
    con.execute("CREATE TABLE ficha_peticoes (numero_inpi VARCHAR, codigo VARCHAR, "
                "descricao VARCHAR, valor VARCHAR, protocolo VARCHAR, data_protocolo VARCHAR)")
    con.execute("CREATE TABLE ipc (numero_inpi VARCHAR, ordem INT, simbolo VARCHAR)")
    con.execute("CREATE TABLE biblio (numero_inpi VARCHAR, data_deposito DATE)")
    con.execute("CREATE TABLE despachos (numero_inpi VARCHAR, data_rpi DATE, "
                "codigo_despacho VARCHAR)")

    con.execute("INSERT INTO procuradores VALUES ('P1','CLARKE MODET'),('P2','CLARKE MODET'),"
                "('P3','OUTRA BANCA')")
    con.execute("INSERT INTO escritorios VALUES ('CLARKE MODET','CLARKE MODET'),"
                "('OUTRA BANCA','OUTRA BANCA')")
    # Clarke tem ficha; OUTRA nao (cobertura 0).
    con.execute("INSERT INTO ficha_extras VALUES ('P1'),('P2')")
    con.execute("""INSERT INTO ficha_anuidades VALUES
        ('P1','3a','OK','G1','$250.00','15/03/2025'),
        ('P1','4a','OK','G2','$250.00','20/03/2025'),
        ('P2','5a','OK','G3','$300.00','10/04/2025'),
        ('P1','6a','OK','G4','921002573202','25/03/2025'),
        ('P2','7a',NULL,NULL,NULL,NULL)
    """)  # 4a linha: GRU vazada no valor (lixo); ultima: sem data (nao paga)
    con.execute("INSERT INTO ipc VALUES ('P1',1,'A61K 9/00'),('P2',1,'B65D 65/46')")

    import inpi.consulta as consulta
    monkeypatch.setattr(consulta, "con", lambda: con)
    consulta._TABELAS = None  # zera cache de tabelas
    # normalizar so devolve a chave; identidade para os dois nomes usados.
    monkeypatch.setattr(m.esc, "normalizar",
                        lambda nome: nome.upper() if nome else "")
    return con


def test_soma_valor_por_mes_com_escritorio_e_periodo(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_estatistica("anuidades_pagas", "soma_valor", agrupar_por="mes",
                           escritorio="Clarke Modet", de="2025-03", ate="2025-03")
    # marco/2025: 250+250 = 500 (a GRU-lixo de marco NAO entra; abril fora do periodo)
    assert r["resultado"] == [{"chave_do_grupo": "2025-03", "valor_da_metrica": 500.0}]
    assert r["total"] == 500.0
    assert r["moeda"] == m.MOEDA


def test_valor_lixo_gru_descartado_e_contado(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_estatistica("anuidades_pagas", "soma_valor",
                           escritorio="Clarke Modet", de="2025-01", ate="2025-12")
    # 250+250+300 = 800; a GRU (bilhoes) descartada, nao somada.
    assert r["total"] == 800.0
    assert r["descartados_invalidos"] == 1


def test_contagem_por_codigo(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_estatistica("anuidades_pagas", "contagem", agrupar_por="codigo",
                           escritorio="Clarke Modet")
    # 4 linhas pagas (com data), uma por codigo/numero de anuidade.
    grupos = {d["chave_do_grupo"]: d["valor_da_metrica"] for d in r["resultado"]}
    assert grupos == {"3a": 1, "4a": 1, "5a": 1, "6a": 1}
    assert r["total"] == 4


def test_erro_valor_em_dataset_sem_valor(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_estatistica("exigencias", "soma_valor")
    assert r.get("erro") is True
    assert "valor" in r["mensagem"].lower()


def test_comparar_com_lado_a_lado_e_cobertura_zero(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_estatistica("anuidades_pagas", "soma_valor",
                           escritorio="Clarke Modet", comparar_com="Outra Banca",
                           de="2025-01", ate="2025-12")
    comp = {c["escritorio"]: c for c in r["comparativo"]}
    assert set(comp) == {"Clarke Modet", "Outra Banca"}
    assert comp["Clarke Modet"]["total"] == 800.0
    # OUTRA nao tem ficha: cobertura 0, total None (nunca 0 silencioso).
    outra = comp["Outra Banca"]
    assert outra["total"] is None
    assert outra["cobertura"]["pedidos_com_ficha_coletada"] == 0
    assert "nao coletado" in outra["cobertura"]["aviso"].lower()


if __name__ == "__main__":
    import types
    mp = types.SimpleNamespace(setattr=lambda o, n, v: setattr(o, n, v))
    for fn in (test_soma_valor_por_mes_com_escritorio_e_periodo,
               test_valor_lixo_gru_descartado_e_contado,
               test_contagem_por_codigo,
               test_erro_valor_em_dataset_sem_valor,
               test_comparar_com_lado_a_lado_e_cobertura_zero):
        fn(mp)
    print("ok")
