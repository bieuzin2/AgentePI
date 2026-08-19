"""Teste offline de inpi_gaps_protecao: incluir_landscape=False e
incluir_familia=False, entao nao bate no BigQuery nem no EPO -- roda so contra a
base INPI local. Acha um titular real com pedido PCT, ancora `hoje` no marco de
fase nacional daquele pedido e confere que ele cai na janela com prazo coerente.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from inpi.db import con
from inpi.gaps_protecao import _cpc_prefixos, inpi_gaps_protecao
from inpi.prazos import inpi_prazo_fase_nacional


def _alvo():
    """Um depositante PEQUENO (poucos PCT, rapido de rodar) com prioridade
    recente, e o pedido cuja prioridade mais recente ancora a janela."""
    return con().execute(
        """
        WITH pct AS (
            SELECT b.numero_inpi, min(pr.data_prioridade) prio
            FROM biblio b JOIN prioridades pr USING (numero_inpi)
            WHERE b.numero_pct IS NOT NULL AND pr.data_prioridade IS NOT NULL
              AND pr.data_prioridade BETWEEN DATE '2022-06-01' AND DATE '2024-12-31'
            GROUP BY 1
        ),
        cont AS (
            SELECT dp.depositante, count(*) n, max(p.prio) prio,
                   arg_max(p.numero_inpi, p.prio) num
            FROM pct p JOIN depositantes dp USING (numero_inpi)
            GROUP BY dp.depositante
        )
        SELECT depositante, prio, num FROM cont
        WHERE n BETWEEN 2 AND 15 ORDER BY prio DESC LIMIT 1
        """
    ).fetchone()


def test_gaps_offline():
    alvo = _alvo()
    if not alvo:
        pytest.skip("base sem pedido PCT com prioridade recente para o teste")
    titular, prio, num = alvo

    # o marco NAO e recalculado no teste: sai do mesmo motor que a funcao usa.
    marco = date.fromisoformat(
        inpi_prazo_fase_nacional(prio.isoformat())["prazos"][0]["prazo"]
    )
    hoje = (marco - timedelta(days=30)).isoformat()

    r = inpi_gaps_protecao(titular, hoje=hoje, incluir_landscape=False,
                           incluir_familia=False)

    assert set(r) >= {"titular", "normalizacao", "parametros",
                      "pedidos_em_janela", "resumo", "avisos"}
    assert r["resumo"]["pedidos_em_risco"] >= 1

    alvos = [p for p in r["pedidos_em_janela"] if p["numero_inpi"] == num]
    assert alvos, f"pedido {num} deveria estar na janela em {hoje}"
    p = alvos[0]
    assert p["marco_fase_nacional"] == marco.isoformat()
    assert p["dias_restantes"] == 30  # hoje = marco - 30 dias
    assert 0 <= p["dias_restantes"] <= r["parametros"]["dias_janela"]
    # offline: sem familia nem landscape, nada de protecao/recomendacao apurada
    assert p["ja_protegido_em"] == []
    assert isinstance(p["paises_importantes_faltando"], list)
    # ordenacao por urgencia (dias_restantes crescente)
    dias = [x["dias_restantes"] for x in r["pedidos_em_janela"]]
    assert dias == sorted(dias)


def test_cpc_prefixos():
    # IPC -> prefixo de 4 chars, distinto e ordenado; ignora simbolo curto/vazio.
    assert _cpc_prefixos(["A61K31/00", "A61K9/00", "B60G", "x", None]) == ["A61K", "B60G"]
