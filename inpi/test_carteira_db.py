"""Regressao: conectar_carteira usa o arquivo local quando NAO ha
MOTHERDUCK_TOKEN no ambiente (isolamento de teste depende disso -- ver
conftest.py da raiz, que limpa o token por padrao para toda a suite).

MotherDuck tem prioridade DE PROPOSITO quando o token existe (ver docstring
de inpi/carteira_db.py: nao ha copia local versionada de tarefas/radar, so a
base compartilhada com o agente remoto) -- por isso este teste NAO simula
token presente (isso contataria o MotherDuck de verdade). O que se testa
aqui e exatamente o caminho que os testes de tarefas.py/radar.py dependem:
sem token no ambiente, 'banco' local e sempre respeitado.
"""

from __future__ import annotations

from inpi.carteira_db import conectar_carteira


def test_usa_arquivo_local_quando_sem_motherduck_token(tmp_path, monkeypatch):
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    banco = tmp_path / "carteira.duckdb"

    c = conectar_carteira(banco)
    try:
        c.execute("CREATE TABLE marcador AS SELECT 'arquivo_local' AS origem")
    finally:
        c.close()

    assert banco.exists()
