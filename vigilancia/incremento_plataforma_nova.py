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
from inpi.mercado import _chave_escritorio
from vigilancia.sync_motherduck import _colunas

# A carteira e o unico alvo legitimo da recoleta: escrever ficha_extras com
# escritorio_canonico='CLARKE MODET' em processo de outra banca e corromper
# dado, e a base nacional inteira (1M+ processos) nao cabe numa rodada semanal.
ESCRITORIO_PADRAO = "CLARKE MODET"

# Teto por rodada da rede de seguranca mensal: mesmo uma carteira recem-
# onboardada (dezenas de milhares de processos nunca coletados) nao pode
# inundar uma unica execucao -- o resto entra nas rodadas seguintes.
LIMITE_WATERMARK = 300

# Subconsulta de escopo compartilhada por numeros_despacho_novo/
# numeros_watermark_vencido -- mesmo JOIN que inpi/benchmark_mercado.py usa.
_SQL_CARTEIRA = """SELECT p.numero_inpi FROM procuradores p
                   JOIN escritorios e ON e.original = p.procurador
                   WHERE e.chave = ?"""

# Path proprio, mesmo calculo que vigilancia/reingestao.py e
# vigilancia/sync_motherduck.py ja fazem cada um por conta -- os tres modulos
# ficam desacoplados de proposito (nenhum importa BANCO_ANTERIOR dos outros).
BANCO_ANTERIOR = BANCO_INPI.with_name("inpi_anterior.duckdb")

# Task Scheduler nao herda o .env -- mesmo padrao de vigilancia/sync_motherduck.py.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def numeros_despacho_novo(escritorio_canonico: str = ESCRITORIO_PADRAO) -> list[str]:
    """DISTINCT numero_inpi DA CARTEIRA cujas linhas de despachos sao novas
    nesta rodada (EXCEPT linha inteira contra inpi_anterior.duckdb -- mesma
    tecnica de vigilancia.sync_motherduck._diff_tabela, so keyed por
    numero_inpi em vez de subir a linha inteira pro MotherDuck). Sem
    inpi_anterior.duckdb (primeira rodada, ou o sync ja consumiu e apagou),
    devolve [] -- sem base para diff, nao ha erro a levantar.

    O escopo por carteira nao e otimizacao: sem ele o diff devolve os ~4 mil
    despachos novos do pais inteiro por semana e rodar_incremento gravaria
    escritorio_canonico='CLARKE MODET' em processo de outra banca. Sem teto
    proprio -- a carteira ja limita a ordem de grandeza (dezenas por semana)."""
    import duckdb

    if not BANCO_ANTERIOR.exists() or not BANCO_INPI.exists():
        return []
    con = duckdb.connect(str(BANCO_INPI), read_only=True)
    try:
        antigo = str(BANCO_ANTERIOR).replace("'", "''")
        con.execute(f"ATTACH '{antigo}' AS antigo (READ_ONLY)")
        cols = ", ".join(_colunas(con, "despachos"))
        linhas = con.execute(
            f"SELECT DISTINCT numero_inpi FROM ("
            f"SELECT {cols} FROM despachos EXCEPT SELECT {cols} FROM antigo.despachos"
            f") WHERE numero_inpi IN ({_SQL_CARTEIRA})",
            [_chave_escritorio(escritorio_canonico)],
        ).fetchall()
        return [r[0] for r in linhas]
    finally:
        con.close()


def rodar_incremento(numeros_inpi: list[str],
                     escritorio_canonico: str = ESCRITORIO_PADRAO) -> dict:
    """Roda coletar_com_fallback_pepi sobre `numeros_inpi` com um cliente
    autenticado novo. Login/senha vem de INPI_PAG_LOGIN/INPI_PAG_PASSWORD --
    mesma env var que inpi/validar_plataforma_nova.py usa. Sem numeros ou sem
    credencial, devolve {"pulado": True, ...} sem tentar rede -- mesma
    convencao de vigilancia.sync_motherduck.sincronizar() para
    MOTHERDUCK_TOKEN ausente."""
    if not numeros_inpi:
        return {"pulado": True, "mensagem": "nenhum numero_inpi na lista de prioridade."}
    login = os.environ.get("INPI_PAG_LOGIN")
    senha = os.environ.get("INPI_PAG_PASSWORD")
    if not login or not senha:
        return {"pulado": True, "mensagem": "INPI_PAG_LOGIN/INPI_PAG_PASSWORD ausentes."}

    from inpi.coleta_plataforma_nova import coletar_com_fallback_pepi
    from inpi.plataforma_nova import ClientePlataformaNova

    cliente = ClientePlataformaNova(login, senha)
    try:
        # atualizar=True: recoleta e o proposito aqui -- sem isso registrar()
        # descarta quem ja esta no CSV e o coletado_em nunca avanca (C1).
        return coletar_com_fallback_pepi(cliente, numeros_inpi, escritorio_canonico,
                                         atualizar=True)
    finally:
        cliente.fechar()


def numeros_watermark_vencido(dias: int = 60,
                              escritorio_canonico: str = ESCRITORIO_PADRAO,
                              limite: int = LIMITE_WATERMARK) -> list[str]:
    """numero_inpi DA CARTEIRA sem coleta da plataforma nova ha mais de `dias`,
    ou nunca coletados, no maximo `limite` por rodada (mais antigos primeiro).
    Rede de seguranca mensal (spec: despacho novo nao correlaciona 100% com
    mudanca real -- ver docstring do modulo).

    Sem o escopo por carteira isto varre a base nacional inteira e entrega
    ~750 mil numeros pro coletor; sem o teto, uma carteira recem-onboardada
    (tudo nunca coletado) faria uma rodada so tentar dezenas de milhares de
    fichas."""
    import duckdb

    if not BANCO_INPI.exists():
        return []
    con = duckdb.connect(str(BANCO_INPI), read_only=True)
    try:
        linhas = con.execute(
            f"""SELECT b.numero_inpi FROM biblio b
               LEFT JOIN ficha_extras f USING (numero_inpi)
               WHERE b.numero_inpi IN ({_SQL_CARTEIRA})
                 AND (f.numero_inpi IS NULL
                      OR try_strptime(f.coletado_em, '%Y-%m-%d')
                         < current_date - INTERVAL (?) DAY)
               ORDER BY f.coletado_em NULLS FIRST
               LIMIT ?""",
            [_chave_escritorio(escritorio_canonico), dias, limite],
        ).fetchall()
        return [r[0] for r in linhas]
    finally:
        con.close()
