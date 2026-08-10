from __future__ import annotations

import enriquecimento.db as db
import enriquecimento.store as store


def _usar_banco_temporario(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "BANCO", tmp_path / "enriquecimento.duckdb")
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    db.fechar()
    yield
    db.fechar()


def test_gravar_e_ler_claims(monkeypatch, tmp_path):
    list(_usar_banco_temporario(monkeypatch, tmp_path))

    store.gravar_claims(
        "102022010731", fonte="google_patents", doc_id="BR102022010731A2",
        reivindicacoes=[{"numero": 1, "texto": "uma luva"}], status="ok",
    )
    lido = store.ler_claims("102022010731")

    assert lido["status"] == "ok"
    assert lido["doc_id"] == "BR102022010731A2"
    assert lido["reivindicacoes"] == [{"numero": 1, "texto": "uma luva"}]


def test_ler_claims_inexistente_devolve_none(monkeypatch, tmp_path):
    list(_usar_banco_temporario(monkeypatch, tmp_path))

    assert store.ler_claims("000000000000") is None


def test_gravar_claims_e_idempotente(monkeypatch, tmp_path):
    """Gravar duas vezes o mesmo número não duplica linha -- é isso que
    permite reenriquecer sem acumular lixo."""
    list(_usar_banco_temporario(monkeypatch, tmp_path))

    store.gravar_claims("102022010731", fonte="google_patents", doc_id="A",
                         reivindicacoes=[{"numero": 1, "texto": "x"}], status="ok")
    store.gravar_claims("102022010731", fonte="familia_epo", doc_id="B",
                         reivindicacoes=[{"numero": 1, "texto": "y"}], status="ok")

    con = db.con()
    total = con.execute(
        "SELECT count(*) FROM claims WHERE numero_normalizado = ?",
        ["102022010731"],
    ).fetchone()[0]
    assert total == 1
    assert store.ler_claims("102022010731")["fonte"] == "familia_epo"


def test_gravar_e_ler_citacoes(monkeypatch, tmp_path):
    list(_usar_banco_temporario(monkeypatch, tmp_path))

    store.gravar_citacoes("102022010731", fonte="google_patents", citacoes=[
        {"tipo": "citando", "doc_citado": "US1234567A"},
        {"tipo": "citada_por", "doc_citado": "US7654321B2"},
    ])
    lidas = store.ler_citacoes("102022010731")

    assert len(lidas) == 2
    assert {c["doc_citado"] for c in lidas} == {"US1234567A", "US7654321B2"}


def test_gravar_citacoes_substitui_por_fonte(monkeypatch, tmp_path):
    list(_usar_banco_temporario(monkeypatch, tmp_path))

    store.gravar_citacoes("102022010731", fonte="google_patents",
                           citacoes=[{"tipo": "citando", "doc_citado": "US1A"}])
    store.gravar_citacoes("102022010731", fonte="google_patents",
                           citacoes=[{"tipo": "citando", "doc_citado": "US2A"}])

    lidas = store.ler_citacoes("102022010731")
    assert [c["doc_citado"] for c in lidas] == ["US2A"]
