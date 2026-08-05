"""Ponte entre o cache de landscape (BigQuery) e o dashboard do escritorio
(plano-v2 4.3/4.6): so le do cache local, NUNCA dispara consulta ao BigQuery.

O dashboard e regenerado com frequencia (vigilancia/executar.py) e nao pode
depender de credencial/rede do Google estarem disponiveis nem gastar quota
so por causa de uma renderizacao. Se nao houver nada em cache ainda (ex.:
usuario nao rodou nenhuma consulta landscape, ou ADC nao configurado), a
secao do dashboard cai no placeholder de sempre -- fallback gracioso.
"""

from __future__ import annotations

from landscape import cache


def resumo_para_dashboard() -> dict | None:
    """Ultimo resultado de cada consulta landscape ja cacheada, ou None se o
    cache ainda estiver vazio/ausente."""
    try:
        con = cache._conectar()
        linhas = con.execute(
            "SELECT chave, resultado, criado_em FROM landscape_cache "
            "ORDER BY criado_em DESC"
        ).fetchall()
    except Exception:
        return None
    if not linhas:
        return None
    import json
    return {
        "fonte": "Google Patents Public Data (patents-public-data.patents.publications)",
        "consultas_cacheadas": len(linhas),
        "mais_recente": json.loads(linhas[0][1]),
        "gerado_em": str(linhas[0][2]),
    }


def demo() -> None:
    """Self-check: cache vazio -> None; cache com dado -> resumo."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        cache._con = None
        cache.BANCO = Path(tmp) / "cache.duckdb"
        assert resumo_para_dashboard() is None
        cache.salvar("evolucao_temporal", {"cpc_prefix": "H01L"}, {"linhas": [1, 2]})
        r = resumo_para_dashboard()
        assert r["consultas_cacheadas"] == 1
    print("OK  fallback gracioso quando vazio, resumo quando ha cache")


if __name__ == "__main__":
    demo()
