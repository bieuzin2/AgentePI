"""Testes de inpi/saude.py -- score do titular real (base INPI), mockado para
determinismo. Exterior (EPO) so roda para cliente curado ou incluir_exterior=True."""

from datetime import date
from unittest.mock import patch

import inpi.saude as sd


def _estados(specs):
    """specs: lista de (encerrado_em, data_deposito). Monta o dict de estados
    no formato que _carregar_lote devolve (so os campos que saude usa)."""
    return {
        f"BR{i}": {"encerrado_em": enc, "data_deposito": dep, "despachos": []}
        for i, (enc, dep) in enumerate(specs)
    }


def _patch_titular(nivel="automatica"):
    return patch.multiple(
        "inpi.titulares",
        chave_de=lambda nome: "CHAVE",
        resolver=lambda chave: {"nivel": nivel, "chave": chave},
    )


def test_titular_sem_processo_e_erro_nao_zero():
    with patch.object(sd, "_carregar_lote", return_value=({}, 0)), _patch_titular():
        r = sd.carteira_saude("FANTASMA")
    assert r["erro"] is True and "nao e zero" not in r["mensagem"].lower()


def test_score_soma_os_quatro_componentes():
    estados = _estados([(None, date(2020, 1, 1)), (None, date(2018, 1, 1)),
                        ("2021-01-01", date(2015, 1, 1)), ("2022-01-01", None)])
    with patch.object(sd, "_carregar_lote", return_value=(estados, 4)), \
         patch.object(sd, "_subclasses_ipc", return_value=4), _patch_titular():
        r = sd.carteira_saude("Cliente", hoje="2026-08-07", incluir_exterior=False)
    soma = sum(c["pontos"] for c in r["componentes"].values())
    assert r["score"] == round(soma, 1)
    assert 0 <= r["score"] <= 100
    # 2 de 4 ativos -> vigencia 20; 3 de 4 com data -> qualidade 22.5
    assert r["componentes"]["vigencia"]["pontos"] == 20.0
    assert r["componentes"]["qualidade_dos_dados"]["pontos"] == 22.5
    # 4 subclasses de teto 8 -> diversidade 7.5
    assert r["componentes"]["diversidade_tecnologica"]["pontos"] == 7.5


def test_componentes_nunca_excedem_o_teto():
    estados = _estados([(None, date(2025, 1, 1))])
    with patch.object(sd, "_carregar_lote", return_value=(estados, 1)), \
         patch.object(sd, "_subclasses_ipc", return_value=99), _patch_titular():
        r = sd.carteira_saude("Cliente", hoje="2026-08-07", incluir_exterior=False)
    for comp in r["componentes"].values():
        assert comp["pontos"] <= comp["de"]


def test_exterior_nao_roda_para_titular_automatico():
    estados = _estados([(None, date(2020, 1, 1))])
    with patch.object(sd, "_carregar_lote", return_value=(estados, 1)), \
         patch.object(sd, "_subclasses_ipc", return_value=2), \
         patch.object(sd, "_exterior") as ext, _patch_titular("automatica"):
        r = sd.carteira_saude("Cliente")  # incluir_exterior=None -> automatico
    ext.assert_not_called()
    assert "nao consultado" in r["exterior"]["nota"]


def test_exterior_roda_automatico_para_cliente_curado():
    estados = _estados([(None, date(2020, 1, 1))])
    with patch.object(sd, "_carregar_lote", return_value=(estados, 1)), \
         patch.object(sd, "_subclasses_ipc", return_value=2), \
         patch.object(sd, "_exterior", return_value={"casos_auditados": 1}) as ext, \
         _patch_titular("curada"):
        r = sd.carteira_saude("Cliente Curado")
    ext.assert_called_once()
    assert r["exterior"] == {"casos_auditados": 1}


def test_incluir_exterior_true_forca_mesmo_automatico():
    estados = _estados([(None, date(2020, 1, 1))])
    with patch.object(sd, "_carregar_lote", return_value=(estados, 1)), \
         patch.object(sd, "_subclasses_ipc", return_value=2), \
         patch.object(sd, "_exterior", return_value={"x": 1}) as ext, \
         _patch_titular("automatica"):
        sd.carteira_saude("Cliente", incluir_exterior=True)
    ext.assert_called_once()
