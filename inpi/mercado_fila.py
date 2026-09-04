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

import csv as _csv
from datetime import date
from pathlib import Path

import duckdb

from inpi.titulares import chaves_de
from landscape.carteira_bridge import landscape_carteira

RAIZ = Path(__file__).resolve().parent
BANCO_FILA = RAIZ / "data" / "fila_mercado.duckdb"
CLIENTES_CURADOS = RAIZ / "referencias" / "clientes-clarke.csv"


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


def _numeros_do_titular(con: duckdb.DuckDBPyConnection, chave: str) -> list[str]:
    """numero_inpi distintos cujo titular casa a chave canonica -- mesma
    tabela `titulares` que inpi.titulares.chaves_de ja usa pra resolver."""
    return [r[0] for r in con.execute(
        """SELECT DISTINCT dp.numero_inpi FROM depositantes dp
           JOIN titulares t ON t.original = dp.depositante
           WHERE t.chave = ?""",
        [chave],
    ).fetchall()]


def popular_concorrentes(top_cpc: int = 3,
                         limite_titulares_por_cpc: int = 10) -> dict:
    """Deriva concorrentes via landscape_carteira() sobre os clientes
    curados da Clarke Modet (inpi/referencias/clientes-clarke.csv): para
    cada cliente, pega os titulares que mais depositam nas mesmas
    tecnologias (CPC) dele no mundo todo (BigQuery), resolve cada nome pra
    chave canonica na base INPI (inpi.titulares.chaves_de), e insere o
    portfolio BR desses titulares na fila com origem='concorrente'.

    Requer ADC do BigQuery configurado -- sem isso landscape_carteira ja
    levanta RuntimeError com instrucao clara (comportamento existente)."""
    if not CLIENTES_CURADOS.exists():
        return {"inseridos": 0, "titulares_resolvidos": 0,
                "titulares_nao_resolvidos": []}

    with CLIENTES_CURADOS.open(encoding="utf-8") as fh:
        clientes = [r["nome_exibicao"] for r in _csv.DictReader(fh)]

    con_inpi = _con_inpi()
    numeros_novos: set[str] = set()
    resolvidos = 0
    nao_resolvidos: list[str] = []
    try:
        for cliente_nome in clientes:
            resultado = landscape_carteira(cliente=cliente_nome, top_cpc=top_cpc)
            for info in resultado.get("por_cpc", {}).values():
                for linha in info.get("top_titulares_mundiais", [])[:limite_titulares_por_cpc]:
                    nome_titular = linha.get("titular")
                    if not nome_titular:
                        continue
                    candidatos = chaves_de(nome_titular)
                    if not candidatos:
                        nao_resolvidos.append(nome_titular)
                        continue
                    resolvidos += 1
                    chave = candidatos[0]["chave"]
                    numeros_novos.update(_numeros_do_titular(con_inpi, chave))
    finally:
        con_inpi.close()

    con = _con()
    try:
        existentes = {r[0] for r in con.execute(
            "SELECT numero_inpi FROM fila_mercado"
        ).fetchall()}
        novos = numeros_novos - existentes
        if novos:
            agora = date.today().isoformat()
            con.executemany(
                "INSERT INTO fila_mercado VALUES (?, 'concorrente', 'pendente', 0, ?)",
                [(n, agora) for n in novos],
            )
        return {"inseridos": len(novos), "titulares_resolvidos": resolvidos,
                "titulares_nao_resolvidos": nao_resolvidos}
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
