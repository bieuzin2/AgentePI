"""inpi_exigencias_stats: media de exigencias/pedido, dias ate 1a exigencia e
comparativo. Banco em memoria montado a mao -- nao depende do dump real."""

from __future__ import annotations

import duckdb

from inpi import exigencias_stats as m


def _con_fake(monkeypatch):
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE procuradores (numero_inpi VARCHAR, procurador VARCHAR)")
    con.execute("CREATE TABLE escritorios (original VARCHAR, chave VARCHAR)")
    con.execute("CREATE TABLE biblio (numero_inpi VARCHAR, data_deposito DATE)")
    con.execute("CREATE TABLE despachos (numero_inpi VARCHAR, data_rpi DATE, "
                "codigo_despacho VARCHAR)")
    con.execute("CREATE TABLE ipc (numero_inpi VARCHAR, simbolo VARCHAR)")

    # A: 2 pedidos -> A1 com 2 exigencias, A2 com 0. media = 2/2 = 1.0
    con.execute("INSERT INTO procuradores VALUES "
                "('A1','CLARKE MODET'),('A2','CLARKE MODET'),('B1','CONCORRENTE')")
    con.execute("INSERT INTO escritorios VALUES "
                "('CLARKE MODET','CLARKE MODET'),('CONCORRENTE','CONCORRENTE')")
    con.execute("INSERT INTO biblio VALUES "
                "('A1',DATE '2020-01-01'),('A2',DATE '2020-06-01'),"
                "('B1',DATE '2020-01-01')")
    con.execute("INSERT INTO ipc VALUES ('A1','A61K 1/00'),('A2','C08L 1/00'),"
                "('B1','A61K 1/00')")
    con.execute("INSERT INTO despachos VALUES "
                # A1: 1a exigencia 100 dias apos deposito, 2a depois (6.1 e 2.5)
                "('A1',DATE '2020-04-10','6.1'),"   # +100 dias
                "('A1',DATE '2020-08-01','2.5'),"
                "('A1',DATE '2020-09-01','9.1'),"   # nao-exigencia, ignorado
                # B1: 1 exigencia, 200 dias apos deposito
                "('B1',DATE '2020-07-19','7.1')")   # +200 dias
    import inpi.consulta as consulta
    monkeypatch.setattr(consulta, "con", lambda: con)
    consulta._TABELAS = None
    monkeypatch.setattr(m.esc, "normalizar",
                        lambda nome: "CONCORRENTE" if "conc" in nome.lower()
                        else "CLARKE MODET")
    return con


def test_media_por_pedido_e_distribuicao(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_exigencias_stats("Clarke Modet")
    assert r["pedidos_considerados"] == 2
    assert r["media_exigencias_por_pedido"] == 1.0   # 2 exigencias / 2 pedidos
    assert r["distribuicao_exigencias"] == {"0": 1, "1": 0, "2": 1, "3+": 0}


def test_dias_ate_primeira_exigencia(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_exigencias_stats("Clarke Modet")
    d = r["dias_ate_primeira_exigencia"]
    assert d["pedidos_com_exigencia"] == 1        # so A1
    assert d["mediana"] == 100                    # deposito 01/01 -> 1a exig 10/04
    assert d["media"] == 100


def test_comparar_com_inclui_base(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_exigencias_stats("Clarke Modet", comparar_com="Concorrente")
    labels = [c["escritorio"] for c in r["comparativo"]]
    assert "Clarke Modet" in labels and "Concorrente" in labels
    assert any(c["chave"] is None for c in r["comparativo"])  # base inteira
    conc = next(c for c in r["comparativo"] if c["escritorio"] == "Concorrente")
    assert conc["dias_mediana"] == 200 and conc["pedidos"] == 1


def test_cpc_restringe(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_exigencias_stats("Clarke Modet", cpc="A61")
    assert r["pedidos_considerados"] == 1          # so A1 (A2 e C08L)
    assert r["media_exigencias_por_pedido"] == 2.0


def test_sem_pedidos_devolve_mensagem(monkeypatch):
    _con_fake(monkeypatch)
    r = m.inpi_exigencias_stats("Clarke Modet", cpc="H99")
    assert r["pedidos_considerados"] == 0
    assert r["media_exigencias_por_pedido"] == 0.0
    assert "mensagem" in r


if __name__ == "__main__":
    import types
    mp = types.SimpleNamespace(setattr=lambda o, n, v: setattr(o, n, v))
    for fn in [test_media_por_pedido_e_distribuicao, test_dias_ate_primeira_exigencia,
               test_comparar_com_inclui_base, test_cpc_restringe,
               test_sem_pedidos_devolve_mensagem]:
        fn(mp)
    print("ok")
