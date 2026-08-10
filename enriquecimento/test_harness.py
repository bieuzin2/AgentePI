from __future__ import annotations

import enriquecimento.db as db
import enriquecimento.harness as harness
from enriquecimento.fontes.google_patents import ResultadoCitacoes, ResultadoClaims


def _usar_banco_temporario(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "BANCO", tmp_path / "enriquecimento.duckdb")
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    db.fechar()
    yield
    db.fechar()


def test_enriquecer_claims_usa_fonte_primaria(monkeypatch, tmp_path):
    list(_usar_banco_temporario(monkeypatch, tmp_path))
    monkeypatch.setattr(
        harness.google_patents, "buscar_claims",
        lambda numero, doc_id=None, idioma="pt": ResultadoClaims(
            ok=True, doc_id="BR102022010731A2",
            reivindicacoes=[{"numero": 1, "texto": "uma luva"}],
        ),
    )

    resultado = harness.enriquecer_claims("102022010731")

    assert resultado["status"] == "ok"
    assert resultado["fonte"] == "google_patents"
    assert resultado["reivindicacoes"] == [{"numero": 1, "texto": "uma luva"}]


def test_enriquecer_claims_cai_para_familia_quando_primaria_falha(monkeypatch, tmp_path):
    list(_usar_banco_temporario(monkeypatch, tmp_path))
    monkeypatch.setattr(
        harness.google_patents, "buscar_claims",
        lambda numero, doc_id=None, idioma="pt": ResultadoClaims(
            ok=False, doc_id=None, mensagem="404 em todos os kind codes",
        ),
    )
    monkeypatch.setattr(
        harness, "buscar_claims_via_familia",
        lambda numero: ResultadoClaims(
            ok=True, doc_id="WO-2023015392-A1", fonte="epo_texto_integral",
            reivindicacoes=[{"numero": 1, "texto": "via familia"}],
        ),
    )

    resultado = harness.enriquecer_claims("102022010731")

    assert resultado["status"] == "ok"
    assert resultado["fonte"] == "epo_texto_integral"


def test_enriquecer_claims_declara_sem_texto_quando_tudo_falha(monkeypatch, tmp_path):
    list(_usar_banco_temporario(monkeypatch, tmp_path))
    monkeypatch.setattr(
        harness.google_patents, "buscar_claims",
        lambda numero, doc_id=None, idioma="pt": ResultadoClaims(
            ok=False, doc_id=None, mensagem="google: nao achou",
        ),
    )
    monkeypatch.setattr(
        harness, "buscar_claims_via_familia",
        lambda numero: ResultadoClaims(ok=False, doc_id=None, mensagem="sem familia WO/EP"),
    )

    resultado = harness.enriquecer_claims("102022010731")

    assert resultado["status"] == "sem_texto"
    assert resultado["reivindicacoes"] == []
    assert "google: nao achou" in resultado["mensagem"]
    assert "sem familia WO/EP" in resultado["mensagem"]


def test_enriquecer_claims_usa_cache_sem_bater_na_rede(monkeypatch, tmp_path):
    list(_usar_banco_temporario(monkeypatch, tmp_path))
    chamadas = []
    monkeypatch.setattr(
        harness.google_patents, "buscar_claims",
        lambda numero, doc_id=None, idioma="pt": (
            chamadas.append(numero) or ResultadoClaims(
                ok=True, doc_id="X", reivindicacoes=[{"numero": 1, "texto": "a"}],
            )
        ),
    )

    harness.enriquecer_claims("102022010731")
    harness.enriquecer_claims("102022010731")

    assert len(chamadas) == 1


def test_enriquecer_citacoes_grava_e_le(monkeypatch, tmp_path):
    list(_usar_banco_temporario(monkeypatch, tmp_path))
    monkeypatch.setattr(
        harness.google_patents, "buscar_citacoes",
        lambda numero, doc_id=None, idioma="en": ResultadoCitacoes(
            ok=True, doc_id="BR102022010731A2",
            citacoes=[{"tipo": "citando", "doc_citado": "US1234567A"}],
        ),
    )

    resultado = harness.enriquecer_citacoes("102022010731")

    assert resultado["mensagem"] is None
    assert resultado["citacoes"] == [
        {"tipo": "citando", "doc_citado": "US1234567A", "fonte": "google_patents",
         "atualizado_em": resultado["citacoes"][0]["atualizado_em"]},
    ]
