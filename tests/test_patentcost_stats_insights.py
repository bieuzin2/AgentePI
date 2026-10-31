"""Estatística por seção IPC e inteligência — banco DuckDB sintético em memória (sem dados reais)."""
import duckdb

from patentcost.insights import montar_insights
from patentcost.stats import estatistica_por_secao


def banco():
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE biblio (numero_inpi VARCHAR, data_deposito DATE)")
    c.execute("CREATE TABLE ipc (numero_inpi VARCHAR, simbolo VARCHAR, ordem INT)")
    c.execute("CREATE TABLE despachos (numero_inpi VARCHAR, codigo_despacho VARCHAR, data_rpi DATE, numero_rpi INT, complemento_despacho VARCHAR)")
    for i in range(40):  # seção C: 40 pedidos decididos; metade com 2 exigências
        n = f"C{i}"
        c.execute("INSERT INTO biblio VALUES (?, DATE '2012-01-01')", [n]); c.execute("INSERT INTO ipc VALUES (?, 'C10G 1/00', 1)", [n])
        c.execute("INSERT INTO despachos VALUES (?, '16.1', DATE '2020-01-01', 1, '')", [n])
        if i % 2 == 0:
            c.execute("INSERT INTO despachos VALUES (?, '6.1', DATE '2017-01-01', 2, ''), (?, '6.1', DATE '2018-01-01', 3, '')", [n, n])
    for i in range(5):  # seção H: amostra pequena
        n = f"H{i}"
        c.execute("INSERT INTO biblio VALUES (?, DATE '2012-01-01')", [n]); c.execute("INSERT INTO ipc VALUES (?, 'H01L 1/00', 1)", [n])
        c.execute("INSERT INTO despachos VALUES (?, '9.2', DATE '2019-01-01', 4, '')", [n])
    c.execute("INSERT INTO biblio VALUES ('P1', DATE '2012-01-01')"); c.execute("INSERT INTO ipc VALUES ('P1', 'C01B 1/00', 1)")  # pendente: fora
    return c


def test_estatistica_por_secao():
    rows = {r["secao"]: r for r in estatistica_por_secao("2010-01-01", "2014-12-31", banco())}
    c = rows["C"]
    assert (c["n"], c["prob_exigencia"], c["media_exigencias"]) == (40, 0.5, 2.0)
    assert 59 <= c["meses_ate_exame"] <= 61 and 95 <= c["meses_ate_concessao"] <= 97
    assert rows["H"]["n"] == 5 and rows["H"]["prob_exigencia"] == 0.0
    assert all(r["jurisdicao"] == "BR" and r["periodo"] == "2010-01-01–2014-12-31" for r in rows.values())


def test_insights_agrupa_por_familia():
    casos = [
        {"familia": "F1", "jurisdicao": "BR", "numero_pedido": "1", "status": "concedida", "data_deposito": "2015-01-01", "data_concessao": "2019-01-01", "categoria_tecnologica": "E", "ipc_cpc": "E21B", "titulo": "T", "confianca": "confirmado"},
        {"familia": "F1", "jurisdicao": "US", "numero_pedido": "2", "status": "pendente", "data_deposito": "2016-01-01", "confianca": "inferido"},
        {"familia": "F2", "jurisdicao": "BR", "numero_pedido": "3", "status": "pendente", "data_deposito": "2020-01-01", "categoria_tecnologica": "C", "confianca": "confirmado"},
    ]
    i = montar_insights(casos, "SINT", [{"name": "SINT", "coverage": "teste"}], ["g"])
    assert i["format"] == "patentcost-insights-1" and i["client"] == "SINT" and i["gaps"] == ["g"]
    f1 = next(f for f in i["families"] if f["id"] == "F1")
    assert (f1["section"], f1["first_filing"], len(f1["members"])) == ("E", "2015-01-01", 2)
    assert f1["members"][0] == {"jurisdiction": "BR", "number": "1", "status": "concedida", "filing": "2015-01-01", "grant": "2019-01-01", "confidence": "confirmado"}
