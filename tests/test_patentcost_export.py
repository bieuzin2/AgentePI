"""Exportador PatentCost — funções puras e classificação do AgentePI (sem banco nem rede; dados sintéticos)."""
from pathlib import Path

import pytest
from openpyxl import load_workbook

from patentcost.export import casos_familia, classificar_status, conciliar, data_iso, escrever_xlsx, modalidade_de, secao_ipc

MODELO = Path(r"C:\Users\Gabriel\Desktop\PatentCost\dist\PatentCost_Modelo_Entrada.xlsx")


def d(codigo, data, rpi, compl=""):
    return {"codigo_despacho": codigo, "data_rpi": data, "numero_rpi": rpi, "complemento_despacho": compl}


def test_status_pela_classificacao_do_agentepi():
    conc = [d("16.1", "2018-06-15", 2475)]
    assert classificar_status("X", conc) == ("concedida", "2018-06-15")
    assert classificar_status("X", [d("9.1", "2018-07-01", 2477)]) == ("concedida", "2018-07-01")  # carta-patente
    # 21.6 é terminal (extinção por anuidade) ...
    assert classificar_status("X", conc + [d("21.6", "2026-07-14", 2897)])[0] == "extinta"
    # ... mas a anulação publicada depois o desfaz (caso PI0803071 documentado no AgentePI)
    anul = conc + [d("21.6", "2026-07-14", 2897), d("21.8", "2026-07-21", 2898, "Anulada a publicação código 21.6 na RPI 2897 de 14/07/2026")]
    assert classificar_status("X", anul)[0] == "concedida"
    # indeferimento revertido por recurso provido não fica encerrado
    assert classificar_status("X", [d("9.2", "2019-01-01", 2500), d("100", "2023-01-01", 2700)])[0] == "pendente"
    assert classificar_status("X", [d("11.2", "2019-01-01", 2500)])[0] == "abandonada"
    assert classificar_status("X", []) == ("pendente", None)


def test_modalidade_secao_e_data():
    assert modalidade_de("102018001234") == "PI" and modalidade_de("202018001234") == "MU"
    assert modalidade_de("PI0803071") == "PI" and modalidade_de("MU8901234") == "MU"
    assert modalidade_de("112019000001") == "PI" and modalidade_de("212019000001") == "MU" and modalidade_de("C10803071") == "PI"
    assert modalidade_de("MI6501234") is None and modalidade_de("302019000001") is None
    assert secao_ipc("E21B 43/26") == "E" and secao_ipc(None) is None and secao_ipc("") is None
    assert data_iso("20190201") == "2019-02-01" and data_iso("2019-02-01") == "2019-02-01" and data_iso(None) is None


FAM = {"familia_id": "55555", "membros": [
    {"pais": "BR", "numero": "102019000001", "kind": "A2", "data_deposito": "20190201", "data_publicacao": "20200801", "concedida": False},
    {"pais": "US", "numero": "2021001", "numero_pedido": "16999999", "kind": "A1", "data_deposito": "20190201", "data_publicacao": "20210110", "concedida": False},
    {"pais": "US", "numero": "11223344", "numero_pedido": "16999999", "kind": "B2", "data_deposito": "20190201", "data_publicacao": "20220510", "concedida": True},
    {"pais": "EP", "numero": "3999999", "numero_pedido": "19900001", "kind": "A1", "data_deposito": "20190201", "data_publicacao": "20241010", "concedida": False},
    {"pais": "CN", "numero": "1000", "numero_pedido": "2019800001", "kind": "A", "data_deposito": "20190201", "data_publicacao": "20150101", "concedida": False},
    {"pais": "WO", "numero": "2020123", "kind": "A1", "data_deposito": "20190201", "data_publicacao": "20200801", "concedida": False},
]}


def test_familia_vira_casos_inferidos(monkeypatch):
    monkeypatch.setattr("patentcost.export.familia", lambda n: FAM)
    base = [{"id_caso": "BR-102019000001", "numero_pedido": "102019000001", "cliente": "SINT", "modalidade": "PI",
             "familia": "102019000001", "categoria_tecnologica": "C", "ipc_cpc": "C10G 1/00"}]
    out, rel = casos_familia(base, hoje="2026-10-31")
    assert sorted(c["jurisdicao"] for c in out) == ["EP", "US"]  # BR, WO e CN antigo não concedido fora; US A1+B2 = um caso
    us = next(c for c in out if c["jurisdicao"] == "US")
    assert (us["status"], us["data_concessao"], us["numero_pedido"], us["confianca"], us["familia"]) == ("concedida", "2022-05-10", "16999999", "inferido", "55555")
    assert base[0]["familia"] == "55555"  # caso BR passa a usar o id INPADOC
    assert (rel["wo_ignorados"], rel["antigos_nao_concedidos"], rel["duplicados"]) == (1, 1, 1)


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
