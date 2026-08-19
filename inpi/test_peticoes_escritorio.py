"""inpi_peticoes_escritorio: conta peticao REALMENTE protocolada (ficha do pePI),
com destaque para cumprimento de exigencia (207) que a RPI nao publica."""

from __future__ import annotations

import duckdb

from inpi import peticoes_escritorio as m


def _con_fake(monkeypatch):
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE procuradores (numero_inpi VARCHAR, procurador VARCHAR)")
    con.execute("CREATE TABLE escritorios (original VARCHAR, chave VARCHAR)")
    con.execute("CREATE TABLE ficha_extras (numero_inpi VARCHAR)")
    con.execute("CREATE TABLE ficha_peticoes (numero_inpi VARCHAR, codigo VARCHAR, "
                "descricao VARCHAR, banco VARCHAR, valor VARCHAR, protocolo VARCHAR, "
                "data_protocolo VARCHAR)")
    con.execute("INSERT INTO procuradores VALUES ('P1','CLARKE MODET'),('P2','CLARKE MODET')")
    con.execute("INSERT INTO escritorios VALUES ('CLARKE MODET','CLARKE MODET')")
    con.execute("INSERT INTO ficha_extras VALUES ('P1'),('P2')")
    con.execute("""INSERT INTO ficha_peticoes VALUES
        ('P1','207','Cumprimento de exigencia','','','X1','15/03/2025'),
        ('P2','207','Cumprimento de exigencia','','','X2','20/06/2025'),
        ('P1','203','Pedido de exame','','','X3','10/03/2025'),
        ('P1','207','Cumprimento de exigencia','','','X4','01/01/2024')
    """)
    import inpi.consulta as consulta
    monkeypatch.setattr(consulta, "con", lambda: con)
    consulta._TABELAS = None
    monkeypatch.setattr(m.esc, "normalizar", lambda nome: "CLARKE MODET")
    return con


def test_filtra_por_codigo_e_periodo(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_peticoes_escritorio("Clarke Modet", codigos=["207"], de="2025-01", ate="2025-12")
    assert r["total_peticoes"] == 2  # os dois 207 de 2025, nao o de 2024, nao o 203
    assert r["por_codigo"] == [
        {"codigo": "207", "descricao": "Cumprimento de exigencia", "quantidade": 2}]


def test_sem_codigo_agrupa_todas(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_peticoes_escritorio("Clarke Modet", de="2025-01", ate="2025-12")
    assert r["total_peticoes"] == 3  # 2x207 + 1x203 em 2025
    codigos = {c["codigo"]: c["quantidade"] for c in r["por_codigo"]}
    assert codigos == {"207": 2, "203": 1}


def test_declara_cobertura(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_peticoes_escritorio("Clarke Modet")
    assert r["cobertura"]["pedidos_com_ficha_coletada"] == 2
    assert "nao coletado" in r["cobertura"]["aviso"].lower()


if __name__ == "__main__":
    import types
    mp = types.SimpleNamespace(setattr=lambda o, n, v: setattr(o, n, v))
    test_filtra_por_codigo_e_periodo(mp)
    test_sem_codigo_agrupa_todas(mp)
    test_declara_cobertura(mp)
    print("ok")
