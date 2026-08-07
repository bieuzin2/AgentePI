"""Gargalos INPI: tempo por fase do exame, backlog de pendentes e comparativo
de pipeline do escritorio vs a base geral -- plano-v2 Fase 1.

VALIDACAO EMPIRICA DOS CODIGOS (rodada em 2026-08-06 contra inpi.duckdb, 987.381
processos com despacho): o marco de deposito usa `biblio.data_deposito`, NAO o
despacho '1.1' -- apenas 47 de 987 mil processos tem os codigos '1.1' e '3.1'
presentes ao mesmo tempo (quase mutuamente exclusivos na pratica, ao contrario
da hipotese inicial do plano). Com `biblio.data_deposito` como origem, a
publicacao (despacho '3.1') ocorre depois do deposito em 360.601 de 360.651
casos (99,98%) -- marco confiavel.
Demais codigos ja documentados e validados em inpi/anuidades.py e
inpi/referencias/prazos-observados.md:
  3.1      publicacao do pedido            (360.651 processos)
  6.1/7.1  1o parecer / exigencia tecnica  (288.438 processos, o que vier primeiro)
  9.1      concessao (carta-patente)       (300.575 processos)
  9.2      indeferimento                   (91.401 processos)
"""

from __future__ import annotations

from datetime import date

from inpi import escritorios as esc
from inpi.consulta import _linhas
from inpi.mcp_app import mcp

_COD_PUBLICACAO = "d.codigo_despacho = '3.1'"
_COD_PARECER = "d.codigo_despacho IN ('6.1','7.1')"
_COD_CONCESSAO = "d.codigo_despacho = '9.1'"
_COD_INDEFERIMENTO = "d.codigo_despacho = '9.2'"


def _carregar_marcos(ipc_prefix: str | None = None, desde: str | None = None,
                      ate: str | None = None, procurador: str | None = None) -> list[dict]:
    """Um marco por processo: data de deposito e primeira data de cada fase
    seguinte que ja ocorreu (None se ainda nao ocorreu)."""
    filtros = ["b.data_deposito IS NOT NULL"]
    params: list = []
    joins = ""
    if ipc_prefix:
        joins += " JOIN (SELECT DISTINCT numero_inpi FROM ipc WHERE simbolo LIKE ?) ai USING (numero_inpi)"
        params.append(f"{ipc_prefix.strip()}%")
    if procurador:
        joins += """ JOIN (SELECT DISTINCT p.numero_inpi FROM procuradores p
                      JOIN escritorios e ON e.original = p.procurador
                      WHERE e.chave = ?) ap USING (numero_inpi)"""
        params.append(esc.normalizar(procurador))
    if desde:
        filtros.append("b.data_deposito >= ?")
        params.append(desde)
    if ate:
        filtros.append("b.data_deposito <= ?")
        params.append(ate)

    sql = f"""
        SELECT b.numero_inpi, b.data_deposito dep,
               min(d.data_rpi) FILTER (WHERE {_COD_PUBLICACAO}) pub,
               min(d.data_rpi) FILTER (WHERE {_COD_PARECER}) parecer,
               min(d.data_rpi) FILTER (WHERE {_COD_CONCESSAO}) concessao,
               min(d.data_rpi) FILTER (WHERE {_COD_INDEFERIMENTO}) indeferimento
        FROM biblio b
        LEFT JOIN despachos d USING (numero_inpi)
        {joins}
        WHERE {" AND ".join(filtros)}
        GROUP BY b.numero_inpi, b.data_deposito
    """
    return _linhas(sql, params)


def _estatisticas_dias(marcos: list[dict], origem: str, destino: str) -> dict | None:
    """Mediana/p25/p75 de dias entre duas colunas de marco, so sobre processos
    onde AMBAS ja ocorreram (e destino nao e anterior a origem, defensivo)."""
    dias = sorted(
        (m[destino] - m[origem]).days
        for m in marcos
        if m.get(origem) and m.get(destino) and m[destino] >= m[origem]
    )
    if not dias:
        return None
    n = len(dias)
    return {
        "casos": n,
        "mediana_dias": dias[n // 2],
        "p25_dias": dias[n // 4],
        "p75_dias": dias[(n * 3) // 4],
    }


@mcp.tool()
def inpi_tempo_fases(ipc_prefix: str | None = None, desde: str | None = None,
                     ate: str | None = None, procurador: str | None = None) -> dict:
    """Tempo mediano (p25/p75, em dias) entre fases do exame: deposito,
    publicacao, 1o parecer/exigencia, concessao ou indeferimento.

    USE QUANDO: precisar de municao para gerenciar expectativa de cliente
    ("quanto tempo falta para sair parecer nessa area?") ou priorizar pedido
    de exame prioritario.

    Args:
        ipc_prefix: prefixo IPC opcional (ex. 'A61K'), filtra a tecnologia.
        desde/ate: 'AAAA-MM-DD' opcionais, filtram por data de deposito.
        procurador: nome do escritorio opcional, filtra a carteira dele.
    """
    marcos = _carregar_marcos(ipc_prefix, desde, ate, procurador)
    if not marcos:
        return {"erro": True, "mensagem": "Nenhum processo encontrado com esse filtro."}
    return {
        "criterio": {"ipc_prefix": ipc_prefix, "desde": desde, "ate": ate,
                     "procurador": procurador, "processos_avaliados": len(marcos)},
        "deposito_para_publicacao": _estatisticas_dias(marcos, "dep", "pub"),
        "publicacao_para_parecer": _estatisticas_dias(marcos, "pub", "parecer"),
        "parecer_para_concessao": _estatisticas_dias(marcos, "parecer", "concessao"),
        "parecer_para_indeferimento": _estatisticas_dias(marcos, "parecer", "indeferimento"),
        "deposito_para_concessao": _estatisticas_dias(marcos, "dep", "concessao"),
        "nota": (
            "Mediana calculada so sobre processos que JA completaram cada "
            "transicao -- pedidos ainda em tramite nao entram aqui (ver "
            "inpi_backlog para eles). E observacao historica da base, nao SLA "
            "publicado pelo INPI."
        ),
    }


@mcp.tool()
def inpi_backlog(ipc_prefix: str | None = None, procurador: str | None = None) -> dict:
    """Pendentes (sem concessao nem indeferimento na base) agrupados por
    tempo decorrido desde o deposito.

    USE QUANDO: priorizar quais casos cobrar exame prioritario, ou dar
    panorama de carteira parada ha muito tempo sem decisao final.
    """
    marcos = _carregar_marcos(ipc_prefix, None, None, procurador)
    if not marcos:
        return {"erro": True, "mensagem": "Nenhum processo encontrado com esse filtro."}

    hoje = date.today()
    faixas = {"0-1 ano": 0, "1-2 anos": 0, "2-4 anos": 0, "4-8 anos": 0, "8+ anos": 0}
    pendentes = 0
    for m in marcos:
        if m.get("concessao") or m.get("indeferimento"):
            continue
        pendentes += 1
        anos = (hoje - m["dep"]).days / 365
        if anos < 1:
            faixas["0-1 ano"] += 1
        elif anos < 2:
            faixas["1-2 anos"] += 1
        elif anos < 4:
            faixas["2-4 anos"] += 1
        elif anos < 8:
            faixas["4-8 anos"] += 1
        else:
            faixas["8+ anos"] += 1

    return {
        "criterio": {"ipc_prefix": ipc_prefix, "procurador": procurador,
                     "processos_avaliados": len(marcos)},
        "pendentes": pendentes,
        "por_tempo_desde_deposito": faixas,
        "nota": (
            "'Pendente' = sem despacho 9.1 (concessao) nem 9.2 (indeferimento) na "
            "base local. Nao distingue arquivado (11.1/11.2) de efetivamente em "
            "tramite -- confira inpi_processo do caso antes de agir."
        ),
    }


@mcp.tool()
def inpi_pipeline_comparado(procurador: str, ipc_prefix: str | None = None) -> dict:
    """Compara o tempo mediano de fase da carteira de UM escritorio contra a
    media da base geral, na mesma tecnologia se informada.

    USE QUANDO: quiser saber se o escritorio esta mais rapido/lento que a
    media do INPI para conversar com cliente sobre expectativa.

    Args:
        procurador: nome do escritorio (carteira a comparar).
        ipc_prefix: prefixo IPC opcional, restringe a comparacao a uma tecnologia.
    """
    marcos_escritorio = _carregar_marcos(ipc_prefix, None, None, procurador)
    if not marcos_escritorio:
        return {"erro": True,
                "mensagem": f"Nenhum processo encontrado para procurador={procurador!r}."}
    marcos_geral = _carregar_marcos(ipc_prefix, None, None, None)

    transicoes = [
        ("deposito_para_publicacao", "dep", "pub"),
        ("publicacao_para_parecer", "pub", "parecer"),
        ("deposito_para_concessao", "dep", "concessao"),
    ]
    comparativo = {
        nome: {
            "escritorio": _estatisticas_dias(marcos_escritorio, origem, destino),
            "media_inpi": _estatisticas_dias(marcos_geral, origem, destino),
        }
        for nome, origem, destino in transicoes
    }
    return {
        "procurador": procurador, "ipc_prefix": ipc_prefix,
        "processos_escritorio": len(marcos_escritorio),
        "processos_base_geral": len(marcos_geral),
        "comparativo": comparativo,
        "nota": "Mediana sobre processos que completaram a transicao em cada grupo.",
    }
