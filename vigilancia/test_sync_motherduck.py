"""Testes do sync local -> MotherDuck (sem rede: conexao mockada)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import vigilancia.sync_motherduck as sync


def test_sem_token_pula(monkeypatch):
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    r = sync.sincronizar()
    assert r == {"ok": False, "pulado": True,
                 "mensagem": "MOTHERDUCK_TOKEN ausente -- sync pulado."}


def test_sobe_so_o_inpi(monkeypatch, tmp_path):
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "tok")
    inpi_db = tmp_path / "inpi.duckdb"
    inpi_db.touch()
    monkeypatch.setattr(sync, "BANCO_INPI", inpi_db)

    con = MagicMock()
    with patch.object(sync.duckdb, "connect", return_value=con) as connect:
        r = sync.sincronizar()

    assert r["ok"] and r["enviados"] == ["inpi (completo)"]
    assert "motherduck_token=tok" in connect.call_args[0][0]
    sqls = [c.args[0] for c in con.execute.call_args_list]
    assert any(s.startswith("CREATE OR REPLACE DATABASE inpi FROM") for s in sqls)
    # carteira (tarefas/casos) NUNCA sobrescrita pelo sync
    assert not any("carteira" in s for s in sqls)
    assert not any("tarefas" in s for s in sqls)
    con.close.assert_called_once()


def test_falha_de_rede_nao_levanta(monkeypatch):
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "tok")
    with patch.object(sync.duckdb, "connect", side_effect=OSError("rede fora")):
        r = sync.sincronizar()
    assert r["ok"] is False and "rede fora" in r["mensagem"]
