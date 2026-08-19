"""Testes de fto.py -- sem rede (incluir_exterior=False), dados reais da base local."""

from __future__ import annotations

from inpi.fto import _tipo_entrada, fto_dominio_publico

HOJE = "2026-08-19"


def test_tipo_entrada():
    assert _tipo_entrada("BR 10 2012 010731 2") == "referencia"
    assert _tipo_entrada("PI0803071") == "referencia"
    assert _tipo_entrada("EP1234567") == "referencia"
    assert _tipo_entrada("Petrobras") == "titular"
    assert _tipo_entrada("Clarke Modet") == "titular"


def test_pedido_antigo_expirado_e_livre_no_brasil():
    # PI0311980: deposito 2003-06-30, sem despacho terminal -> a vigencia do art. 40
    # (20 anos) termina em 2023 -> morto por TEMPO no BR. Sem exterior, BR morto =>
    # LIVRE_NO_BRASIL (nunca DOMINIO_PUBLICO_GLOBAL sem confirmar o exterior).
    r = fto_dominio_publico("PI0311980", incluir_exterior=False, hoje=HOJE)
    assert r["tipo_entrada"] == "referencia"
    (item,) = r["itens"]
    assert item["situacao_fto"] == "LIVRE_NO_BRASIL"
    assert item["evidencia"]["br"]["vivo"] is False
    assert "art. 40" in item["evidencia"]["br"]["motivo"]
    assert r["resumo"]["dominio_publico_global"] == 0  # sem exterior, nao se afirma global


def test_pedido_recente_ativo_requer_licenca():
    # 102020000017: deposito 2020, sem despacho terminal, dentro da vigencia -> vivo no BR.
    r = fto_dominio_publico("102020000017", incluir_exterior=False, hoje=HOJE)
    (item,) = r["itens"]
    assert item["situacao_fto"] == "REQUER_LICENCA"
    assert item["evidencia"]["br"]["vivo"] is True


def test_shape_do_contrato():
    r = fto_dominio_publico("PI0311980", incluir_exterior=False, hoje=HOJE)
    assert set(r) >= {"entrada", "tipo_entrada", "itens", "resumo", "avisos"}
    assert set(r["resumo"]) == {"dominio_publico_global", "livre_no_brasil", "requer_licenca"}
    item = r["itens"][0]
    assert set(item) >= {"referencia", "situacao_fto", "evidencia", "base_legal",
                         "confianca", "links"}
    assert "espacenet" in item["links"] and "inpi" in item["links"]
    # o aviso de que e orientativo (nao parecer juridico) sempre esta presente
    assert any("parecer juridico" in a for a in r["avisos"])
    # incluir_exterior=False deve avisar que o veredito global fica indisponivel
    assert any("DOMINIO_PUBLICO_GLOBAL" in a for a in r["avisos"])
