"""Testes da proveniencia de titular (curada vs automatica)."""

from __future__ import annotations

import pytest

import inpi.titulares as tit


@pytest.fixture
def clientes_csv(tmp_path, monkeypatch):
    csv = tmp_path / "clientes-clarke.csv"
    csv.write_text(
        "chave_canonica,nome_exibicao,processos,grafias\n"
        "MOTOROLA,\"Motorola, Inc.\",1057,28\n"
        "MOTOROLA MOBILITY,\"Motorola Mobility, LLC\",496,11\n"
        "CNPJ:33000167,Petroleo Brasileiro S.A. - Petrobras,505,6\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tit, "CLIENTES", csv)
    monkeypatch.setattr(tit, "_cache_clientes", None)
    yield csv
    tit._cache_clientes = None


def test_resolver_cliente_curado(clientes_csv):
    r = tit.resolver("MOTOROLA")
    assert r["nivel"] == "curada"
    assert r["nome_exibicao"] == "Motorola, Inc."


def test_resolver_titular_qualquer_e_automatica(clientes_csv):
    r = tit.resolver("ACME LTDA")
    assert r["nivel"] == "automatica"
    assert "confira" in r["nota"]


def test_resolver_chave_nula(clientes_csv):
    assert tit.resolver(None)["nivel"] == "automatica"


def test_csv_ausente_nao_quebra(tmp_path, monkeypatch):
    monkeypatch.setattr(tit, "CLIENTES", tmp_path / "nao-existe.csv")
    monkeypatch.setattr(tit, "_cache_clientes", None)
    assert tit.resolver("MOTOROLA")["nivel"] == "automatica"
    tit._cache_clientes = None


def test_relacionados_mesmo_prefixo_nunca_somados(clientes_csv):
    rel = tit.relacionados("MOTOROLA")
    assert [r["chave"] for r in rel] == ["MOTOROLA MOBILITY"]
    assert all(r["nao_somados_na_contagem"] for r in rel)


def test_relacionados_prefixo_curto_vazio(clientes_csv):
    # 'CNPJ:' vira prefixo '33000167' -- sem outro cliente com essa raiz, vazio
    assert tit.relacionados("CNPJ:33000167") == []
    assert tit.relacionados(None) == []
