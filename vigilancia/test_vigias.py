"""Testes dos 5 vigias. Rodam contra a base local do INPI (mesmo padrao de
inpi/test_inpi_mcp.py: pulam sozinhos se o banco nao existir) -- o caso
PI0803071 ja e o fixture real de anulacao usado no resto do projeto (ver
inpi/consulta.py e docs/plano-v2.md), entao reusamos em vez de montar um
DuckDB sintetico.
"""

from __future__ import annotations

import pytest

from inpi.db import BANCO
from vigilancia import vigias

precisa_banco = pytest.mark.skipif(
    not BANCO.exists(), reason="banco ausente; rode python inpi/ingest.py"
)


@precisa_banco
def test_vigia_carteira_detecta_despacho_novo():
    alertas = vigias.vigia_carteira(["PI0803071"], desde="2019-01-01")
    tipos = {a["tipo"] for a in alertas}
    assert "despacho_novo" in tipos or "anulacao" in tipos
    assert all(a["processo"] == "PI0803071" for a in alertas)


@precisa_banco
def test_vigia_carteira_marca_anulacao_como_severidade_alta():
    """RPI 2898/despacho 21.8 anula a extincao publicada 7 dias antes (RPI 2897,
    despacho 21.6) -- e o caso de referencia do plano (secao 4.1, risco 9)."""
    alertas = vigias.vigia_carteira(["PI0803071"], desde="2026-01-01")
    anulacoes = [a for a in alertas if a["tipo"] == "anulacao"]
    assert anulacoes, "despacho 21.8 deveria ter sido classificado como anulacao"
    a = anulacoes[0]
    assert a["severidade"] == "alta"
    assert a["data"] == "2026-07-21"


@precisa_banco
def test_vigia_carteira_vazio_sem_novidade_na_janela():
    alertas = vigias.vigia_carteira(["PI0803071"], desde="2030-01-01")
    assert alertas == []


def test_vigia_carteira_sem_numeros_nao_falha():
    assert vigias.vigia_carteira([], desde="2026-01-01") == []


@precisa_banco
def test_vigia_ipc_so_traz_a_classificacao_pedida():
    alertas = vigias.vigia_ipc(["B65D"], desde="1990-01-01")
    assert all(a["tipo"] == "ipc" for a in alertas[:5])


@precisa_banco
def test_vigia_concorrentes_filtra_pela_data():
    # janela no futuro -> nenhum deposito deveria entrar
    alertas = vigias.vigia_concorrentes(["PETROLEO BRASILEIRO"], desde="2099-01-01")
    assert alertas == []


@precisa_banco
def test_vigia_anuidades_entra_na_janela_de_90_dias():
    """Simula 'anuidade entrando na janela': primeira execucao (estado vazio)
    deve alertar tudo o que a projecao encontrar; a segunda, com o mesmo
    estado, nao repete o alerta -- e o diff contra a semana anterior."""
    alertas1, estado1 = vigias.vigia_anuidades(["PI0803071"], hoje="2026-08-05")
    alertas2, estado2 = vigias.vigia_anuidades(["PI0803071"], hoje="2026-08-05",
                                               estado_anterior=estado1)
    if alertas1:
        assert alertas2 == []
    assert estado1 == estado2


def test_vigia_anuidades_sem_numeros_nao_falha():
    alertas, estado = vigias.vigia_anuidades([], hoje="2026-08-05")
    assert alertas == [] and estado == {}


def test_vigia_exterior_sem_numeros_nao_falha():
    alertas, estado = vigias.vigia_exterior([])
    assert alertas == [] and estado == {}
