"""Prioriza a coleta incremental da plataforma nova (inpi/coleta_plataforma_nova.py):
so processos com sinal de mudanca real, nao a carteira inteira.

Duas fontes de prioridade (spec:
docs/superpowers/specs/2026-09-04-inpi-incremento-e-migracao-design.md):
  - numeros_despacho_novo(): despacho novo no dump semanal -- sinal primario,
    calculado ANTES de vigilancia.sync_motherduck.sincronizar_incremental()
    apagar inpi_anterior.duckdb (a copia que vigilancia.reingestao ja deixa
    antes de recriar o banco).
  - numeros_watermark_vencido(): rede de seguranca mensal, cobre mudanca sem
    despacho correspondente (achado da validacao ao vivo 2026-09-04: despacho
    novo NAO correlaciona 100% com mudanca real na plataforma nova).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from inpi.db import BANCO as BANCO_INPI
from vigilancia.sync_motherduck import _colunas

# Path proprio, mesmo calculo que vigilancia/reingestao.py e
# vigilancia/sync_motherduck.py ja fazem cada um por conta -- os tres modulos
# ficam desacoplados de proposito (nenhum importa BANCO_ANTERIOR dos outros).
BANCO_ANTERIOR = BANCO_INPI.with_name("inpi_anterior.duckdb")

# Task Scheduler nao herda o .env -- mesmo padrao de vigilancia/sync_motherduck.py.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def numeros_despacho_novo() -> list[str]:
    """DISTINCT numero_inpi cujas linhas de despachos sao novas nesta rodada
    (EXCEPT linha inteira contra inpi_anterior.duckdb -- mesma tecnica de
    vigilancia.sync_motherduck._diff_tabela, so keyed por numero_inpi em vez
    de subir a linha inteira pro MotherDuck). Sem inpi_anterior.duckdb
    (primeira rodada, ou o sync ja consumiu e apagou), devolve [] -- sem base
    para diff, nao ha erro a levantar."""
    import duckdb

    if not BANCO_ANTERIOR.exists() or not BANCO_INPI.exists():
        return []
    con = duckdb.connect(str(BANCO_INPI))
    try:
        antigo = str(BANCO_ANTERIOR).replace("'", "''")
        con.execute(f"ATTACH '{antigo}' AS antigo (READ_ONLY)")
        cols = ", ".join(_colunas(con, "despachos"))
        linhas = con.execute(
            f"SELECT DISTINCT numero_inpi FROM ("
            f"SELECT {cols} FROM despachos EXCEPT SELECT {cols} FROM antigo.despachos"
            f")"
        ).fetchall()
        return [r[0] for r in linhas]
    finally:
        con.close()


def numeros_watermark_vencido(dias: int = 60) -> list[str]:
    """numero_inpi de biblio sem coleta da plataforma nova ha mais de `dias`,
    ou nunca coletados. Rede de seguranca mensal (spec: despacho novo nao
    correlaciona 100% com mudanca real -- ver docstring do modulo)."""
    import duckdb

    if not BANCO_INPI.exists():
        return []
    con = duckdb.connect(str(BANCO_INPI), read_only=True)
    try:
        linhas = con.execute(
            """SELECT b.numero_inpi FROM biblio b
               LEFT JOIN ficha_extras f USING (numero_inpi)
               WHERE f.numero_inpi IS NULL
                  OR try_strptime(f.coletado_em, '%Y-%m-%d') < current_date - INTERVAL (?) DAY""",
            [dias],
        ).fetchall()
        return [r[0] for r in linhas]
    finally:
        con.close()
