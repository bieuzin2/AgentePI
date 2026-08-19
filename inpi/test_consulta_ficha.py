"""Regressao: inpi_processo carrega os extras raspados do pePI (CPC, peticoes,
anuidades pagas) e a renumeracao/vinculos quando existem para o pedido.

Roda contra o banco real (read-only). Se a coleta de ficha nao cobriu nenhum
pedido neste ambiente, os asserts especificos sao pulados -- o que importa e que
inpi_processo nunca quebra por causa das tabelas ficha_*/renumeracoes ausentes.
"""

from __future__ import annotations

import pytest

from inpi import consulta as c


def test_tem_tabela_nao_quebra_com_tabela_inexistente():
    # A garantia central: checar tabela ausente devolve False, nao excecao.
    assert c._tem_tabela("tabela_que_nunca_existiu") is False


def test_inpi_processo_inclui_cpc_quando_ha_ficha():
    if not c._tem_tabela("ficha_extras"):
        pytest.skip("ficha_extras nao existe neste banco")
    achado = c._linhas(
        "SELECT numero_inpi FROM ficha_extras WHERE cpc IS NOT NULL "
        "AND cpc <> '' LIMIT 1"
    )
    if not achado:
        pytest.skip("nenhum pedido com CPC coletado")
    num = achado[0]["numero_inpi"]
    ficha = c.inpi_processo(num)
    assert not ficha.get("erro"), ficha
    assert "cpc" in ficha and ficha["cpc"]


def test_ficha_extras_ausente_devolve_dict_vazio():
    # numero_inpi improvavel de ter ficha -> nao levanta, so vem {}
    assert c._ficha_extras("000000000000") == {}


if __name__ == "__main__":
    test_tem_tabela_nao_quebra_com_tabela_inexistente()
    test_inpi_processo_inclui_cpc_quando_ha_ficha()
    test_ficha_extras_ausente_devolve_dict_vazio()
    print("ok")
