"""parse_valor: dois formatos reais da ficha (anuidade '$1,645.00', peticao
'419.0'), descarte de GRU vazada e de lixo. Guarda a soma contra outlier."""

from __future__ import annotations

from inpi.valores import TETO_SANO, parse_valor


def test_formato_anuidade_milhar_virgula():
    assert parse_valor("$1,645.00") == 1645.0
    assert parse_valor("$2,800.00") == 2800.0
    assert parse_valor("$295.00") == 295.0


def test_formato_peticao_float_cru():
    assert parse_valor("419.0") == 419.0
    assert parse_valor("63.63") == 63.63


def test_rejeita_gru_vazada_e_acima_do_teto():
    assert parse_valor("921002573202") is None
    assert parse_valor(str(TETO_SANO + 1)) is None


def test_rejeita_vazio_nulo_e_lixo():
    assert parse_valor("") is None
    assert parse_valor(None) is None
    assert parse_valor("abc") is None
    assert parse_valor("-5") is None


if __name__ == "__main__":
    test_formato_anuidade_milhar_virgula()
    test_formato_peticao_float_cru()
    test_rejeita_gru_vazada_e_acima_do_teto()
    test_rejeita_vazio_nulo_e_lixo()
    print("ok")
