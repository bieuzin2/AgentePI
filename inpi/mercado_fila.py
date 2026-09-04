"""Fila persistente de enriquecimento de mercado -- CPC/anuidades/peticoes
fora da carteira propria da Clarke Modet, via inpi/plataforma_nova.py.
Arquivo proprio (fila_mercado.duckdb), separado de inpi.duckdb: zero risco
de lock/concorrencia com o job semanal (vigilancia/executar.py).

Duas origens: 'concorrente' (derivado de landscape_carteira sobre os
clientes curados, ver popular_concorrentes) e 'nacional' (resto da base,
so entra quando o usuario decidir expandir, ver popular_nacional).
proximo_lote() sempre prioriza concorrente antes de nacional.

Ver docs/superpowers/specs/2026-09-04-inpi-enriquecimento-mercado-design.md.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent
BANCO_FILA = RAIZ / "data" / "fila_mercado.duckdb"


def _con() -> duckdb.DuckDBPyConnection:
    BANCO_FILA.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(BANCO_FILA))
    con.execute("""
        CREATE TABLE IF NOT EXISTS fila_mercado (
            numero_inpi VARCHAR,
            origem VARCHAR,
            status VARCHAR,
            tentativas INTEGER,
            atualizado_em VARCHAR
        )
    """)
    return con


def proximo_lote(n: int) -> list[str]:
    """Ate `n` numero_inpi pendentes, concorrente antes de nacional."""
    con = _con()
    try:
        linhas = con.execute(
            """SELECT numero_inpi FROM fila_mercado
               WHERE status = 'pendente'
               ORDER BY CASE origem WHEN 'concorrente' THEN 0 ELSE 1 END,
                        numero_inpi
               LIMIT ?""",
            [n],
        ).fetchall()
        return [r[0] for r in linhas]
    finally:
        con.close()


def _con_inpi() -> duckdb.DuckDBPyConnection:
    from inpi.db import BANCO as BANCO_INPI
    return duckdb.connect(str(BANCO_INPI), read_only=True)


def popular_nacional(desde: str = "2020-01-01") -> dict:
    """Insere na fila (origem='nacional') todo numero_inpi de biblio com
    deposito >= `desde` que ainda nao esta na fila (de qualquer origem) --
    so roda quando o usuario decidir expandir alem dos concorrentes."""
    con_inpi = _con_inpi()
    try:
        numeros = [r[0] for r in con_inpi.execute(
            "SELECT numero_inpi FROM biblio WHERE data_deposito >= ?", [desde]
        ).fetchall()]
    finally:
        con_inpi.close()

    con = _con()
    try:
        existentes = {r[0] for r in con.execute(
            "SELECT numero_inpi FROM fila_mercado"
        ).fetchall()}
        novos = [n for n in numeros if n not in existentes]
        if novos:
            agora = date.today().isoformat()
            con.executemany(
                "INSERT INTO fila_mercado VALUES (?, 'nacional', 'pendente', 0, ?)",
                [(n, agora) for n in novos],
            )
        return {"inseridos": len(novos)}
    finally:
        con.close()


def marcar(numeros_inpi: list[str], status: str) -> None:
    """Atualiza status em lote (ex.: apos uma rodada de coleta)."""
    if not numeros_inpi:
        return
    con = _con()
    try:
        agora = date.today().isoformat()
        placeholders = ", ".join("?" * len(numeros_inpi))
        con.execute(
            f"""UPDATE fila_mercado
                SET status = ?, atualizado_em = ?,
                    tentativas = tentativas + 1
                WHERE numero_inpi IN ({placeholders})""",
            [status, agora, *numeros_inpi],
        )
    finally:
        con.close()
