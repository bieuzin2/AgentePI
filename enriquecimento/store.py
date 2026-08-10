"""Leitura/escrita idempotente das tabelas de enriquecimento (claims, citações).

Escrita é sempre DELETE+INSERT por chave: o harness roda on-demand e pode
reenriquecer o mesmo número (nova fonte, fallback que passou a funcionar,
etc.) -- delete+insert evita linha duplicada ou desatualizada sem depender de
UPSERT/ON CONFLICT.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from enriquecimento.db import con


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def gravar_claims(numero_normalizado: str, fonte: str, doc_id: str | None,
                   reivindicacoes: list[dict], status: str, mensagem: str = "") -> None:
    """status: 'ok' (reivindicações preenchidas), 'sem_texto' (nenhuma fonte
    achou texto integral -- nunca inventa) ou 'falha' (erro de rede/parse)."""
    c = con()
    c.execute("DELETE FROM claims WHERE numero_normalizado = ?", [numero_normalizado])
    c.execute(
        "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            numero_normalizado, fonte, doc_id,
            json.dumps(reivindicacoes, ensure_ascii=False),
            status, mensagem, _agora(),
        ],
    )


def ler_claims(numero_normalizado: str) -> dict | None:
    c = con()
    linha = c.execute(
        "SELECT fonte, doc_id, reivindicacoes_json, status, mensagem, atualizado_em "
        "FROM claims WHERE numero_normalizado = ?",
        [numero_normalizado],
    ).fetchone()
    if linha is None:
        return None
    fonte, doc_id, reiv_json, status, mensagem, atualizado_em = linha
    return {
        "numero_normalizado": numero_normalizado,
        "fonte": fonte,
        "doc_id": doc_id,
        "reivindicacoes": json.loads(reiv_json),
        "status": status,
        "mensagem": mensagem,
        "atualizado_em": atualizado_em,
    }


def gravar_citacoes(numero_normalizado: str, fonte: str, citacoes: list[dict]) -> None:
    """citacoes: lista de {'tipo': 'citando'|'citada_por', 'doc_citado': str}."""
    c = con()
    c.execute(
        "DELETE FROM citacoes WHERE numero_normalizado = ? AND fonte = ?",
        [numero_normalizado, fonte],
    )
    agora = _agora()
    for cit in citacoes:
        c.execute(
            "INSERT INTO citacoes VALUES (?, ?, ?, ?, ?)",
            [numero_normalizado, cit["tipo"], cit["doc_citado"], fonte, agora],
        )


def ler_citacoes(numero_normalizado: str) -> list[dict]:
    c = con()
    linhas = c.execute(
        "SELECT tipo, doc_citado, fonte, atualizado_em FROM citacoes "
        "WHERE numero_normalizado = ? ORDER BY tipo, doc_citado",
        [numero_normalizado],
    ).fetchall()
    return [
        {"tipo": t, "doc_citado": d, "fonte": f, "atualizado_em": a}
        for t, d, f, a in linhas
    ]
