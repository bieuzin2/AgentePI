"""Radar de prospeccao: versao INCREMENTAL de inpi_prospeccao, com
marca-dagua de numero_rpi para so trazer titulares que publicaram pedido
NOVO desde a ultima rodada -- plano-v2 Fase 5.

Sem watermark, cada rodada reprocessa a base inteira e reencontra os mesmos
titulares de sempre -- o vigia certo e "o que mudou desde a ultima vez", nao
"quem sao os titulares relevantes hoje" (isso ja existe em inpi_prospeccao,
que continua sendo o retrato completo sob demanda). O watermark fica numa
tabela propria em carteira.duckdb (mesmo banco de tarefas.py), uma linha por
combinacao (escritorio, ipc, uf) -- radares do mesmo escritorio em areas
diferentes avancam independente.

Marco de 'pedido novo' = despacho '3.1' (publicacao do pedido), nao o
deposito: o pedido so fica visivel/pesquisavel apos publicado.
"""

from __future__ import annotations

import duckdb

from inpi import tarefas as tf
from inpi.carteira_db import conectar_carteira
from inpi.consulta import _linhas
from inpi.mcp_app import mcp
from inpi.mercado import _AVISO_PESSOAL, _chave_escritorio
from inpi.tarefas import BANCO as BANCO_TAREFAS

ESQUEMA_RADAR = """
CREATE TABLE IF NOT EXISTS radar_watermark (
    chave         VARCHAR PRIMARY KEY,
    numero_rpi    INTEGER NOT NULL,
    atualizado_em TIMESTAMP NOT NULL DEFAULT current_timestamp
)
"""


def _con_radar(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    c = conectar_carteira(BANCO_TAREFAS, read_only)
    if not read_only:
        c.execute(ESQUEMA_RADAR)
    return c


def _chave_radar(escritorio: str, ipc: str | None, uf: str | None) -> str:
    return "|".join([_chave_escritorio(escritorio), (ipc or "").upper(), (uf or "").upper()])


def _watermark(chave: str) -> int:
    c = _con_radar()
    try:
        row = c.execute(
            "SELECT numero_rpi FROM radar_watermark WHERE chave = ?", [chave]
        ).fetchone()
        return row[0] if row else 0
    finally:
        c.close()


def _salvar_watermark(chave: str, numero_rpi: int) -> None:
    c = _con_radar()
    try:
        c.execute(
            "INSERT OR REPLACE INTO radar_watermark VALUES (?, ?, current_timestamp)",
            [chave, numero_rpi],
        )
    finally:
        c.close()


@mcp.tool()
def inpi_radar(escritorio: str, ipc: str | None = None, uf: str | None = None,
               min_pedidos: int = 1, criar_tarefas: bool = False) -> dict:
    """Radar INCREMENTAL de prospeccao: titulares que publicaram pedido NOVO
    desde a ultima vez que este radar rodou, excluindo quem ja e representado
    pelo escritorio informado.

    USE QUANDO: quiser acompanhar prospeccao de forma continua, sem
    reprocessar a base inteira a cada rodada nem revisitar os mesmos
    titulares repetidos. Para um retrato completo (nao incremental) de quem
    deposita numa area, use inpi_prospeccao.

    Args:
        escritorio: o nosso nome -- quem ja representamos sai da lista.
        ipc: prefixo de classificacao opcional, define a "area" deste radar.
        uf: sigla do estado do depositante, opcional.
        min_pedidos: volume minimo (pedidos publicados NESTA rodada) para
            o titular entrar na lista.
        criar_tarefas: True cria uma tarefa (ver inpi_tarefas) por titular
            novo encontrado, com o processo mais recente como referencia.
    """
    chave_radar = _chave_radar(escritorio, ipc, uf)
    desde_rpi = _watermark(chave_radar)
    chave_nossa = _chave_escritorio(escritorio)

    cond = ["d.codigo_despacho = '3.1'", "d.numero_rpi > ?"]
    params: list = [desde_rpi]
    if ipc:
        cond.append("i.simbolo LIKE ?")
        params.append(f"{ipc.strip()}%")
    if uf:
        cond.append("dp.estado = ?")
        params.append(uf.strip().upper())
    params.append(chave_nossa)

    linhas = _linhas(
        f"""SELECT t.chave titular_chave, arg_max(dp.depositante, 1) titular,
                   any_value(dp.pais) pais, any_value(dp.estado) uf,
                   any_value(dp.tipopessoadepositante) tipo_pessoa,
                   count(DISTINCT d.numero_inpi) pedidos_nesta_rodada,
                   max(d.numero_rpi) numero_rpi_mais_recente,
                   arg_max(d.numero_inpi, d.numero_rpi) processo_mais_recente
            FROM despachos d
            JOIN depositantes dp USING (numero_inpi)
            JOIN titulares t ON t.original = dp.depositante
            LEFT JOIN ipc i USING (numero_inpi)
            WHERE {' AND '.join(cond)}
              AND dp.numero_inpi NOT IN (
                    SELECT p.numero_inpi FROM procuradores p
                    JOIN escritorios e ON e.original = p.procurador
                    WHERE e.chave = ?
              )
            GROUP BY t.chave
            HAVING count(DISTINCT d.numero_inpi) >= ?
            ORDER BY pedidos_nesta_rodada DESC""",
        params + [min_pedidos],
    )

    maior = _linhas(
        "SELECT max(numero_rpi) n FROM despachos WHERE numero_rpi > ?", [desde_rpi]
    )[0]["n"]
    if maior and maior > desde_rpi:
        _salvar_watermark(chave_radar, maior)

    tarefas_criadas = []
    if criar_tarefas:
        for l in linhas:
            r = tf.tarefa_criar(
                f"Prospeccao: {l['titular']} publicou {l['pedidos_nesta_rodada']} "
                f"pedido(s) novo(s) (RPI {l['numero_rpi_mais_recente']})",
                processo=l["processo_mais_recente"],
            )
            tarefas_criadas.append(r["id"])

    tem_pf = any((l.get("tipo_pessoa") or "").lower().startswith("pessoa f") for l in linhas)
    resultado = {
        "escritorio": escritorio, "chave_radar": chave_radar,
        "filtro": {"ipc": ipc, "uf": uf, "min_pedidos": min_pedidos},
        "rodada_anterior_ate_rpi": desde_rpi,
        "rodada_atual_ate_rpi": maior or desde_rpi,
        "titulares_novos": len(linhas),
        "resultados": linhas,
        "tarefas_criadas": tarefas_criadas,
        "nota": (
            "Marco de 'novo' e o despacho 3.1 (publicacao), nao o deposito. "
            "Primeira rodada de um radar (rodada_anterior_ate_rpi=0) traz TODO "
            "o historico publicado que casar com o filtro -- rode uma vez para "
            "estabelecer o watermark antes de usar em producao continua."
        ),
    }
    if tem_pf:
        resultado["aviso_dado_pessoal"] = _AVISO_PESSOAL
    return resultado
