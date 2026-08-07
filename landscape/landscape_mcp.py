"""Servidor MCP 'landscape': patent landscape via Google Patents Public Data
(BigQuery, plano-v2 4.6).

So registra tools; a logica mora em landscape/bigquery_client.py (dry-run +
teto de 10GB), landscape/consultas.py (SQL parametrizado) e landscape/cache.py
(DuckDB, TTL 30 dias).

Requer ADC configurado (`gcloud auth application-default login`) -- sem isso
toda tool aqui levanta RuntimeError com instrucao clara, nunca falha em silencio.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from landscape import cache, consultas
from landscape.bigquery_client import TETO_BYTES_PADRAO, cliente

mcp = FastMCP("landscape")


def _rodar(nome: str, fn, args: dict, *, teto_bytes: int = TETO_BYTES_PADRAO,
           confirmar_acima_10gb: bool = False) -> dict:
    """Cache-first: le do DuckDB (30 dias) antes de bater no BigQuery.

    teto_bytes/confirmar_acima_10gb controlam o teto de 10GB do BigQuery e
    ficam FORA da chave de cache -- so afetam se a consulta roda, nao o que
    ela retorna, entao nao devem gerar entradas de cache diferentes.
    """
    cacheado = cache.obter(nome, args)
    if cacheado is not None:
        cacheado["cache"] = True
        return cacheado
    resultado = fn(cliente(), teto_bytes=teto_bytes,
                    confirmar_acima_10gb=confirmar_acima_10gb, **args)
    resultado["cache"] = False
    cache.salvar(nome, args, resultado)
    return resultado


@mcp.tool()
def landscape_evolucao_temporal(cpc_prefix: str, pais: str | None = None,
                                 desde: str | None = None, ate: str | None = None,
                                 confirmar_acima_10gb: bool = False) -> dict:
    """Evolucao de depositos por ano numa tecnologia (prefixo CPC) e jurisdicao.

    USE QUANDO: precisar ver a trajetoria de deposito de uma tecnologia (ex.
    'H01L' semicondutores) ao longo do tempo, opcionalmente filtrada por pais.

    Fonte: Google Patents Public Data (166M publicacoes, BigQuery). O dataset
    tem atraso de meses em relacao ao deposito real -- nunca tratar como
    tempo real. Sem veredito de mercado; so contagem de documentos.

    Args:
        cpc_prefix: prefixo do codigo CPC, ex. 'H01L' ou 'H01L31/00'.
        pais: codigo de pais ISO2 opcional (ex. 'BR', 'US').
        desde/ate: 'AAAA-MM-DD' opcionais, filtram por data de deposito.
        confirmar_acima_10gb: True para rodar mesmo se a consulta estimar
            mais de 10GB processados (senao levanta ConsultaMuitoGrandeError).
    """
    return _rodar("evolucao_temporal", consultas.evolucao_temporal,
                  {"cpc_prefix": cpc_prefix, "pais": pais, "desde": desde, "ate": ate},
                  confirmar_acima_10gb=confirmar_acima_10gb)


@mcp.tool()
def landscape_top_titulares(cpc_prefix: str, pais: str | None = None,
                             desde: str | None = None, ate: str | None = None,
                             limite: int = 20, confirmar_acima_10gb: bool = False) -> dict:
    """Titulares com mais depositos numa CPC x pais x periodo.

    USE QUANDO: precisar identificar quem mais deposita numa tecnologia/jurisdicao
    -- mapeamento competitivo, nao ranking de qualidade de portfolio.

    Fonte: Google Patents Public Data (assignee_harmonized, BigQuery).

    Args:
        cpc_prefix: prefixo do codigo CPC.
        pais: codigo de pais ISO2 opcional.
        desde/ate: 'AAAA-MM-DD' opcionais.
        limite: 1 a 100 titulares no ranking.
        confirmar_acima_10gb: True para rodar mesmo acima do teto de 10GB.
    """
    return _rodar("top_titulares", consultas.top_titulares,
                  {"cpc_prefix": cpc_prefix, "pais": pais, "desde": desde,
                   "ate": ate, "limite": limite},
                  confirmar_acima_10gb=confirmar_acima_10gb)


@mcp.tool()
def landscape_co_classificacao(cpc_prefix: str, desde: str | None = None,
                                ate: str | None = None, limite: int = 30,
                                confirmar_acima_10gb: bool = False) -> dict:
    """Mapa de co-classificacao: pares de codigos CPC que mais aparecem juntos
    nas mesmas publicacoes de uma tecnologia.

    USE QUANDO: precisar entender interseccao tecnologica (ex. onde 'H01L'
    cruza com outras areas) para desenhar escopo de busca ou landscape.

    Fonte: Google Patents Public Data (BigQuery).

    Args:
        cpc_prefix: prefixo do codigo CPC de partida.
        desde/ate: 'AAAA-MM-DD' opcionais.
        limite: 1 a 100 pares no ranking.
        confirmar_acima_10gb: True para rodar mesmo acima do teto de 10GB.
    """
    return _rodar("co_classificacao", consultas.co_classificacao,
                  {"cpc_prefix": cpc_prefix, "desde": desde, "ate": ate, "limite": limite},
                  confirmar_acima_10gb=confirmar_acima_10gb)


@mcp.tool()
def landscape_perfil_titular(nome_titular: str, desde: str | None = None,
                              ate: str | None = None,
                              confirmar_acima_10gb: bool = False) -> dict:
    """Perfil de um titular: distribuicao tecnologica (CPC) e geografica (pais).

    USE QUANDO: precisar caracterizar o portfolio de um titular especifico --
    nome como aparece em assignee_harmonized (pode nao bater exatamente com o
    nome legal; harmonizacao e do proprio dataset, nao deste projeto).

    Fonte: Google Patents Public Data (BigQuery).

    Args:
        nome_titular: nome do titular conforme assignee_harmonized.
        desde/ate: 'AAAA-MM-DD' opcionais.
        confirmar_acima_10gb: True para rodar mesmo acima do teto de 10GB.
    """
    return _rodar("perfil_titular", consultas.perfil_titular,
                  {"nome_titular": nome_titular, "desde": desde, "ate": ate},
                  confirmar_acima_10gb=confirmar_acima_10gb)


if __name__ == "__main__":
    mcp.run()
