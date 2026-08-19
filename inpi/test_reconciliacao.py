"""Teste de inpi/reconciliacao.py -- shape e contrato, SEM bater na rede EPO.

Roda com pytest ou como __main__. Usa incluir_exterior=False para nao consumir
quota do EPO nem depender de credencial; pega um numero real do banco.
"""

from __future__ import annotations

from inpi.consulta import normaliza_numero
from inpi.db import con
from inpi.reconciliacao import reconciliar


def _um_concedido() -> str:
    """Um numero real com despacho de concessao (9.1) -- exercita o caminho mais rico."""
    r = con().execute(
        "SELECT numero_inpi FROM despachos WHERE codigo_despacho = '9.1' LIMIT 1"
    ).fetchone()
    assert r, "banco sem nenhum despacho 9.1 -- inesperado"
    return r[0]


def test_shape_sem_exterior():
    num = _um_concedido()
    r = reconciliar(num, incluir_exterior=False)

    assert r["numero_inpi"] == normaliza_numero(num)
    assert not r.get("erro"), r

    # Estado INPI: bloco com procedencia e situacao coerente.
    est = r["estado_inpi"]
    assert est["fonte"] == "base INPI local (despachos)"
    assert est["confianca"] == "alta"
    assert est["concedido"] is True  # veio de um 9.1
    assert est["situacao"] in {"concedido_vigente", "concedido_extinto"}

    # Exterior nao consultado quando incluir_exterior=False (nada de rede).
    assert r["familia_exterior"] == {
        "consultado": False,
        "nota": r["familia_exterior"]["nota"],
    }
    assert r["familia_exterior"]["consultado"] is False

    # Contratos de lista.
    assert isinstance(r["divergencias"], list)
    assert isinstance(r["campos_promovidos"], list)
    for d in r["divergencias"]:
        assert {"tipo", "detalhe", "fontes", "acao_sugerida"} <= set(d)
    for c in r["campos_promovidos"]:
        assert "fonte" in c and "confianca" in c

    # Sem exterior, nenhuma divergencia que dependa do EPO pode aparecer.
    tipos_exterior = {"exterior_adiantado", "familia_morta_exterior", "sigilo_vazado_exterior"}
    assert not (tipos_exterior & {d["tipo"] for d in r["divergencias"]})

    assert "base INPI local (despachos)" in r["fontes_consultadas"]


def test_numero_inexistente():
    r = reconciliar("BR000000000000", incluir_exterior=False)
    assert r.get("erro") is True
    assert "numero_inpi" in r


if __name__ == "__main__":
    test_shape_sem_exterior()
    test_numero_inexistente()
    print("ok")
