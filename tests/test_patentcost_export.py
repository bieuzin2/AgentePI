"""Exportador PatentCost — funções puras (sem banco nem rede; dados sintéticos)."""
from pathlib import Path

import pytest
from openpyxl import load_workbook

from patentcost.export import casos_familia, classificar_status, conciliar, data_iso, escrever_xlsx, modalidade_de, secao_ipc

MODELO = Path(r"C:\Users\Gabriel\Desktop\PatentCost\dist\PatentCost_Modelo_Entrada.xlsx")


def d(codigo, data, rpi, compl=""):
    return {"codigo_despacho": codigo, "data_rpi": data, "numero_rpi": rpi, "complemento_despacho": compl}


def test_status_concessao_extincao_e_anulacao():
    conc = [d("16.1", "2018-06-15", 2475)]
    assert classificar_status(conc) == ("concedida", "2018-06-15")
    assert classificar_status(conc + [d("21.6", "2026-07-14", 2897)])[0] == "extinta"
    anulado = conc + [d("21.6", "2026-07-14", 2897), d("21.8", "2026-07-21", 2898, "Anulada a publicação código 21.6 na RPI 2897 de 14/07/2026")]
    assert classificar_status(anulado)[0] == "concedida"
    assert classificar_status([d("11.2", "2019-01-01", 2500)])[0] == "abandonada"
    assert classificar_status([]) == ("pendente", None)


def test_modalidade_secao_e_data():
    assert modalidade_de("102018001234") == "PI" and modalidade_de("202018001234") == "MU"
    assert modalidade_de("PI0803071") == "PI" and modalidade_de("MU8901234") == "MU"
    assert secao_ipc("E21B 43/26") == "E" and secao_ipc(None) is None and secao_ipc("") is None
    assert data_iso("20190201") == "2019-02-01" and data_iso("2019-02-01") == "2019-02-01" and data_iso(None) is None


FAM = {"membros": [
    {"pais": "BR", "numero": "102019000001", "kind": "A2", "data_deposito": "20190201", "data_publicacao": "20200801", "concedida": False},
    {"pais": "US", "numero": "11223344", "kind": "B2", "data_deposito": "20190201", "data_publicacao": "20220510", "concedida": True},
    {"pais": "EP", "numero": "3999999", "kind": "A1", "data_deposito": "20190201", "data_publicacao": "20201010", "concedida": False},
    {"pais": "US", "numero": "11223344", "kind": "B2", "data_deposito": "20190201", "data_publicacao": "20220510", "concedida": True},
]}


def test_familia_vira_casos_inferidos(monkeypatch):
    monkeypatch.setattr("patentcost.export.familia", lambda n: FAM)
    out = casos_familia([{"id_caso": "BR-102019000001", "numero_pedido": "102019000001", "cliente": "SINT", "modalidade": "PI",
                          "familia": "102019000001", "categoria_tecnologica": "C", "ipc_cpc": "C10G 1/00"}])
    assert sorted(c["jurisdicao"] for c in out) == ["EP", "US"]  # BR e duplicado fora
    us = next(c for c in out if c["jurisdicao"] == "US")
    assert (us["status"], us["data_concessao"], us["data_deposito"], us["confianca"], us["familia"]) == ("concedida", "2022-05-10", "2019-02-01", "inferido", "102019000001")


def test_xlsx_no_contrato(tmp_path):
    if not MODELO.exists():
        pytest.skip("modelo do PatentCost ausente (rode npm run template)")
    escrever_xlsx([{"id_caso": "BR-X", "cliente": "SINT", "jurisdicao": "BR", "modalidade": "PI", "tipo_registro": "existente",
                    "numero_pedido": "X", "status": "pendente", "fonte": "INPI", "confianca": "confirmado", "observacoes": "sintético"}], MODELO, tmp_path / "o.xlsx")
    ws = load_workbook(tmp_path / "o.xlsx")["Casos"]
    cab = [c.value for c in ws[1]]
    linha = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, cab.index("id_caso") + 1).value == "BR-X")
    assert ws.cell(linha, cab.index("jurisdicao") + 1).value == "BR"
    assert ws.cell(linha, cab.index("observacoes") + 1).value.startswith("[INPI|confirmado]")


def test_conciliacao():
    r = conciliar([{"numero_pedido": "A", "status": "concedida"}], [{"numero_pedido": "A", "status": "extinta"}, {"numero_pedido": "B"}])
    assert r["apenas_cliente"] == ["B"] and r["apenas_publico"] == []
    assert r["divergencias"] == [{"numero_pedido": "A", "campo": "status", "publico": "concedida", "cliente": "extinta"}]
