"""Testes do sync local -> MotherDuck (sem rede: conexao mockada)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import duckdb

import vigilancia.sync_motherduck as sync


def test_diff_tabela_insere_atualiza_e_remove(tmp_path):
    """_diff_tabela e o coracao do sync incremental: roda ela de verdade contra
    tres arquivos DuckDB locais (novo/antigo/"remoto" -- um arquivo local serve
    de dublê perfeito pro remoto aqui, porque ATTACH nao liga se o outro lado
    e md: ou um .duckdb comum). Cobre os tres casos numa tabela so: uma linha
    nova (id=3), uma linha removida (id=2, so existia no antigo) e uma linha
    alterada (id=1, mesma chave mas 'nome' mudou)."""
    antigo_path = tmp_path / "antigo.duckdb"
    remoto_path = tmp_path / "remoto.duckdb"
    novo_path = tmp_path / "novo.duckdb"

    con_a = duckdb.connect(str(antigo_path))
    con_a.execute("CREATE TABLE t (id INTEGER, nome VARCHAR)")
    con_a.execute("INSERT INTO t VALUES (1, 'antes'), (2, 'so no antigo')")
    con_a.close()

    con_r = duckdb.connect(str(remoto_path))
    con_r.execute("CREATE TABLE t (id INTEGER, nome VARCHAR)")
    con_r.execute("INSERT INTO t VALUES (1, 'antes'), (2, 'so no antigo')")
    con_r.close()

    con = duckdb.connect(str(novo_path))
    con.execute("CREATE TABLE t (id INTEGER, nome VARCHAR)")
    con.execute("INSERT INTO t VALUES (1, 'depois'), (3, 'novo')")
    con.execute(f"ATTACH '{antigo_path.as_posix()}' AS antigo (READ_ONLY)")
    con.execute(f"ATTACH '{remoto_path.as_posix()}' AS remoto")

    r = sync._diff_tabela(con, "t")

    assert r == {"tabela": "t", "inseridos": 2, "removidos": 2}
    final = con.execute("SELECT id, nome FROM remoto.t ORDER BY id").fetchall()
    assert final == [(1, "depois"), (3, "novo")]
    con.close()


def test_incremental_sem_copia_anterior_cai_para_completo(monkeypatch, tmp_path):
    monkeypatch.setattr(sync, "BANCO_ANTERIOR", tmp_path / "nao-existe.duckdb")
    with patch.object(sync, "sincronizar", return_value={"ok": True, "enviados": []}) as m:
        r = sync.sincronizar_incremental()
    m.assert_called_once()
    assert r == {"ok": True, "enviados": [], "modo": "completo (sem copia anterior para comparar)"}


def test_incremental_sem_token_pula(monkeypatch, tmp_path):
    anterior = tmp_path / "inpi_anterior.duckdb"
    anterior.touch()
    monkeypatch.setattr(sync, "BANCO_ANTERIOR", anterior)
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)

    r = sync.sincronizar_incremental()

    assert r == {"ok": False, "pulado": True,
                 "mensagem": "MOTHERDUCK_TOKEN ausente -- sync pulado."}


def test_incremental_conecta_no_banco_novo_e_anexa_antigo_e_remoto(monkeypatch, tmp_path):
    anterior = tmp_path / "inpi_anterior.duckdb"
    anterior.touch()
    novo = tmp_path / "inpi.duckdb"
    novo.touch()
    monkeypatch.setattr(sync, "BANCO_ANTERIOR", anterior)
    monkeypatch.setattr(sync, "BANCO_INPI", novo)
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "tok")

    con = MagicMock()
    con.execute.return_value.fetchall.return_value = []  # SHOW TABLES vazio: nenhuma tabela pra sincronizar
    with patch.object(sync.duckdb, "connect", return_value=con) as connect:
        r = sync.sincronizar_incremental()

    assert connect.call_args[0][0] == str(novo)
    sqls = [c.args[0] for c in con.execute.call_args_list]
    assert any(s.startswith("ATTACH") and "antigo" in s and str(anterior) in s.replace("''", "'")
               for s in sqls)
    assert any(s == "ATTACH 'md:inpi' AS remoto" for s in sqls)
    assert r == {"ok": True, "modo": "incremental", "tabelas": []}
    assert not anterior.exists()  # apagada apos sucesso


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
