"""Regressao: MOTHERDUCK_TOKEN no ambiente NAO pode desviar o store de
enriquecimento do arquivo local quando ele existe.

Mesma causa e mesmo fix de inpi/test_db.py (commit 4602bad): qualquer import
que carregue .env (ex.: inpi.familia_epo, importado por inpi_mcp -> oposicoes)
poe MOTHERDUCK_TOKEN no ambiente do processo inteiro. Sem prioridade correta em
enriquecimento/db.py, isso desviava claims/citacoes recem-gravadas pelo harness
para o MotherDuck (sincronizado manualmente, pode estar atrasado) -- verificado
ao vivo checando o fix de claims cross-jurisdicao: 'import inpi.inpi_mcp'
sozinho ja poluia o ambiente antes de qualquer chamada ao harness.
"""

from __future__ import annotations

import duckdb
import pytest

from enriquecimento import db as m


@pytest.fixture(autouse=True)
def _reseta_conexao_cacheada(monkeypatch):
    monkeypatch.setattr(m, "_con", None)
    yield
    monkeypatch.setattr(m, "_con", None)


def test_arquivo_local_tem_prioridade_sobre_motherduck(tmp_path, monkeypatch):
    banco = tmp_path / "enriquecimento.duckdb"
    con = duckdb.connect(str(banco))
    con.execute("CREATE TABLE marcador AS SELECT 'arquivo_local' AS origem")
    con.close()

    monkeypatch.setattr(m, "BANCO", banco)
    # Token obviamente invalido: se con() tentasse o MotherDuck com ele, a
    # conexao falharia (rede/autenticacao) em vez de devolver a marca local.
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "token-invalido-nao-deveria-ser-usado")

    r = m.con().execute("SELECT origem FROM marcador").fetchone()
    assert r == ("arquivo_local",)


def test_motherduck_e_fallback_quando_arquivo_local_nao_existe(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "BANCO", tmp_path / "nao-existe.duckdb")
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)

    # Sem token e sem arquivo, cai no ramo "else": cria o arquivo local novo
    # (store e cache que pode nascer vazio, ao contrario de inpi/db.py que
    # exige o dump completo existir).
    con = m.con()
    assert (tmp_path / "nao-existe.duckdb").exists()
    tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert {"claims", "citacoes"} <= tabelas
