"""inpi_responsavel_pi: casa dado curado, e devolve encontrado=false com instrucao
de fallback quando nao ha registro. A separacao MCP-vs-internet e a garantia central."""

from __future__ import annotations

from inpi import inteligencia_mercado as m


def test_sem_registro_devolve_encontrado_false_e_instrucao(monkeypatch):
    monkeypatch.setattr(m, "_curados", lambda: [])
    r = m.inpi_responsavel_pi("Empresa Inexistente XYZ")
    assert r["encontrado"] is False
    assert "internet" in r["instrucao_agente"].lower()


def test_casa_por_nome_normalizado(monkeypatch):
    monkeypatch.setattr(m, "_curados", lambda: [
        {"empresa_canonica": "NUBANK", "responsavel_pi": "Ciclana",
         "cargo": "Head de PI", "eventos": "ABPI", "fonte": "linkedin",
         "data_curadoria": "2026-08-19", "observacao": ""},
    ])
    r = m.inpi_responsavel_pi("nubank")
    assert r["encontrado"] is True
    assert r["fonte"] == "curadoria interna"
    assert r["responsaveis"][0]["responsavel_pi"] == "Ciclana"


def test_linha_exemplo_semente_e_ignorada():
    # O CSV real so tem a linha-exemplo -> _curados() deve devolver vazio.
    assert m._curados() == []


if __name__ == "__main__":
    import types
    mp = types.SimpleNamespace(setattr=lambda o, n, v: setattr(o, n, v))
    test_sem_registro_devolve_encontrado_false_e_instrucao(mp)
    test_casa_por_nome_normalizado(mp)
    test_linha_exemplo_semente_e_ignorada()
    print("ok")
