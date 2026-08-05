"""Teste fim a fim de vigilancia/executar.py --dry-run.

Roda contra a base real (--sem-reingestao, para nao baixar CSV em teste) e
verifica que alertas.md e gerado e que o e-mail NAO e enviado de verdade.
"""

from __future__ import annotations

import json

import pytest

from inpi.db import BANCO
from vigilancia import executar

precisa_banco = pytest.mark.skipif(
    not BANCO.exists(), reason="banco ausente; rode python inpi/ingest.py"
)


def test_primeira_terca_do_mes():
    from datetime import date

    assert executar.primeira_terca_do_mes(date(2026, 8, 4))   # 1a terca de agosto/2026
    assert not executar.primeira_terca_do_mes(date(2026, 8, 11))  # 2a terca
    assert not executar.primeira_terca_do_mes(date(2026, 8, 5))   # quarta


@precisa_banco
def test_executar_dry_run_nao_envia_email_e_gera_markdown(tmp_path, monkeypatch):
    banco_teste = tmp_path / "alertas.duckdb"
    md_teste = tmp_path / "alertas.md"
    log_teste = tmp_path / "log.jsonl"
    monkeypatch.setattr(executar, "BANCO", banco_teste)
    monkeypatch.setattr(executar, "ALERTAS_MD", md_teste)
    monkeypatch.setattr(executar, "LOG_EXECUCAO", log_teste)
    monkeypatch.setattr(executar, "ESTADO_ANUIDADES", tmp_path / "estado_anu.json")
    monkeypatch.setattr(executar, "ESTADO_EXTERIOR", tmp_path / "estado_ext.json")

    r = executar.executar(dry_run=True, sem_reingestao=True, hoje="2026-08-05")

    assert not r.get("erro")
    assert md_teste.exists()
    assert r["email"]["enviado"] is False
    assert r["email"].get("dry_run") is True
    assert log_teste.exists()
    linha = json.loads(log_teste.read_text(encoding="utf-8").splitlines()[-1])
    assert linha["sucesso"] is True


@precisa_banco
def test_executar_sem_email_pula_envio(tmp_path, monkeypatch):
    monkeypatch.setattr(executar, "BANCO", tmp_path / "a.duckdb")
    monkeypatch.setattr(executar, "ALERTAS_MD", tmp_path / "a.md")
    monkeypatch.setattr(executar, "LOG_EXECUCAO", tmp_path / "log.jsonl")
    monkeypatch.setattr(executar, "ESTADO_ANUIDADES", tmp_path / "ea.json")
    monkeypatch.setattr(executar, "ESTADO_EXTERIOR", tmp_path / "ee.json")

    r = executar.executar(sem_reingestao=True, sem_email=True, hoje="2026-08-05")
    assert r["email"]["mensagem"] == "sem_email=True"
