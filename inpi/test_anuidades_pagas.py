"""inpi_anuidades_pagas: conta anuidade REALMENTE PAGA (ledger da ficha do pePI),
distinta da projecao. Testa contra banco em memoria montado a mao -- nao depende
da coleta real existir no ambiente."""

from __future__ import annotations

import duckdb

from inpi import anuidades_pagas as m


def _con_fake(monkeypatch):
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE procuradores (numero_inpi VARCHAR, procurador VARCHAR)")
    con.execute("CREATE TABLE escritorios (original VARCHAR, chave VARCHAR)")
    con.execute("CREATE TABLE ficha_extras (numero_inpi VARCHAR)")
    con.execute("CREATE TABLE ficha_anuidades (numero_inpi VARCHAR, numero VARCHAR, "
                "status VARCHAR, gru VARCHAR, valor VARCHAR, data_pagamento VARCHAR)")
    con.execute("INSERT INTO procuradores VALUES ('P1','CLARKE MODET'),('P2','CLARKE MODET')")
    con.execute("INSERT INTO escritorios VALUES ('CLARKE MODET','CLARKE MODET')")
    con.execute("INSERT INTO ficha_extras VALUES ('P1'),('P2')")
    con.execute("""INSERT INTO ficha_anuidades VALUES
        ('P1','3a','OK','G1','$250.00','15/03/2025'),
        ('P1','4a','OK','G2','$250.00','20/03/2025'),
        ('P2','5a','OK','G3','$300.00','10/03/2026'),
        ('P1','6a',NULL,NULL,NULL,NULL)
    """)  # ultima: sem data = nao paga, nao pode contar
    # _linhas e _tem_tabela usam con() de inpi.consulta; escritorios.normalizar
    # so devolve a chave. Monkeypatch os dois pontos de entrada.
    import inpi.consulta as consulta
    monkeypatch.setattr(consulta, "con", lambda: con)
    consulta._TABELAS = None  # zera cache de tabelas
    monkeypatch.setattr(m.esc, "normalizar", lambda nome: "CLARKE MODET")
    return con


def test_conta_so_pagas_no_periodo(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_anuidades_pagas("Clarke Modet", de="2025-03", ate="2025-03")
    assert r["total_anuidades_pagas"] == 2  # as duas de marco/2025, nao a sem data
    assert r["por_mes"] == {"2025-03": 2}


def test_periodo_amplo_agrupa_por_mes(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_anuidades_pagas("Clarke Modet", de="2025-01", ate="2026-12")
    assert r["total_anuidades_pagas"] == 3
    assert r["por_mes"] == {"2025-03": 2, "2026-03": 1}


def test_declara_cobertura(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_anuidades_pagas("Clarke Modet")
    assert r["cobertura"]["pedidos_com_ficha_coletada"] == 2
    assert "nao coletado" in r["cobertura"]["aviso"].lower()


if __name__ == "__main__":
    import types
    mp = types.SimpleNamespace(setattr=lambda o, n, v: setattr(o, n, v))
    test_conta_so_pagas_no_periodo(mp)
    test_periodo_amplo_agrupa_por_mes(mp)
    test_declara_cobertura(mp)
    print("ok")
