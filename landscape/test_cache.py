"""Testes de landscape/cache.py contra banco DuckDB temporario."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from landscape import cache


def test_cache_salva_e_le(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_con", None)
    monkeypatch.setattr(cache, "BANCO", tmp_path / "cache.duckdb")

    assert cache.obter("evolucao_temporal", {"cpc_prefix": "H01L"}) is None
    cache.salvar("evolucao_temporal", {"cpc_prefix": "H01L"}, {"linhas": [1, 2, 3]})
    assert cache.obter("evolucao_temporal", {"cpc_prefix": "H01L"}) == {"linhas": [1, 2, 3]}


def test_cache_distingue_por_argumento(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_con", None)
    monkeypatch.setattr(cache, "BANCO", tmp_path / "cache.duckdb")

    cache.salvar("top_titulares", {"cpc_prefix": "H01L"}, {"linhas": ["a"]})
    assert cache.obter("top_titulares", {"cpc_prefix": "G06F"}) is None


def test_cache_expira_apos_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_con", None)
    monkeypatch.setattr(cache, "BANCO", tmp_path / "cache.duckdb")

    cache.salvar("x", {"a": 1}, {"linhas": []})
    con = cache._conectar()
    antigo = datetime.now(timezone.utc) - timedelta(days=cache.TTL_DIAS + 1)
    con.execute("UPDATE landscape_cache SET criado_em = ?", [antigo.replace(tzinfo=None)])
    assert cache.obter("x", {"a": 1}) is None


def test_modo_leitura_salvar_e_noop_nao_derruba(tmp_path, monkeypatch):
    """Quando o arquivo esta travado por outro processo, o cache abre em leitura:
    obter() ainda serve o gravado, e salvar() vira no-op silencioso -- nunca derruba
    a consulta de landscape que ja rodou."""
    monkeypatch.setattr(cache, "_con", None)
    monkeypatch.setattr(cache, "_somente_leitura", False)
    monkeypatch.setattr(cache, "BANCO", tmp_path / "cache.duckdb")

    cache.salvar("q", {"a": 1}, {"linhas": [1]})            # grava normal (RW)
    assert cache.obter("q", {"a": 1}) == {"linhas": [1]}

    monkeypatch.setattr(cache, "_somente_leitura", True)     # simula queda para leitura
    cache.salvar("q", {"a": 1}, {"linhas": [9, 9]})          # deve ser no-op, sem erro
    assert cache.obter("q", {"a": 1}) == {"linhas": [1]}     # segue o valor antigo
