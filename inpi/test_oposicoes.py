"""Testes do radar de oposicao EP (Register mockado)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import inpi.oposicoes as op


def test_data_aceita_dois_formatos():
    assert op._data("20260101") == date(2026, 1, 1)
    assert op._data("2026-01-01") == date(2026, 1, 1)
    assert op._data(None) is None
    assert op._data("lixo") is None


def test_fim_janela_9_meses():
    assert op._fim_janela(date(2026, 1, 15)) == date(2026, 10, 15)


def _rodar(register, hoje="2026-08-07"):
    estados = {"BR1": {"encerrado_em": None}}
    fam = {"membros": [{"pais": "EP", "referencia": "EP-1-B1"}]}
    with patch.object(op, "_carregar_lote", return_value=(estados, 1)), \
         patch.object(op, "familia", return_value=fam), \
         patch.object(op, "chave_de", return_value="X"), \
         patch.object(op, "resolver", return_value={"nivel": "automatica", "chave": "X"}), \
         patch("epo.epo_mcp.epo_register", return_value=register):
        return op.carteira_oposicoes_ep("Cliente X", hoje=hoje)


def test_janela_aberta_e_oposicao_mencionada():
    r = _rodar({"encontrado": True, "situacao": "Opposition filed",
                "situacao_em": "20260701", "mencao_de_concessao": "20260201"})
    assert len(r["oposicoes_mencionadas"]) == 1
    assert r["janelas_de_oposicao_abertas"][0]["janela_ate"] == "2026-11-01"


def test_janela_fechada_nao_alerta():
    r = _rodar({"encontrado": True, "situacao": "No opposition filed within time limit",
                "situacao_em": "20240101", "mencao_de_concessao": "20230101"})
    assert r["janelas_de_oposicao_abertas"] == []
    assert r["oposicoes_mencionadas"] == []  # 'No opposition filed' menciona...


def test_register_sem_documento_vira_falha():
    r = _rodar({"encontrado": False, "mensagem": "nao tem"})
    assert r["falhas_de_consulta"][0]["numero_inpi"] == "BR1"
    assert r["consultados"] == []
