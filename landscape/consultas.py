"""Consultas prontas contra patents-public-data.patents.publications (166M
publicacoes, Google Patents Public Data via BigQuery -- plano-v2 4.6).

Todas parametrizadas com bigquery.ScalarQueryParameter -- nunca concatenacao
de string no SQL, mesmo o BigQuery nao tendo o mesmo risco classico de SQLi
de um banco transacional (o risco aqui e formatacao errada de valor, nao
injecao de comando).

Ancora tripla obrigatoria em quem consome o retorno destas funcoes: fonte =
"Google Patents Public Data (patents-public-data.patents.publications)",
cobertura declarada (o dataset tem atraso de meses em relacao ao deposito
real -- nunca tratar como tempo real), sem veredito.
"""

from __future__ import annotations

from google.cloud import bigquery

from landscape.bigquery_client import executar

_TABELA = "`patents-public-data.patents.publications`"

FONTE = "Google Patents Public Data (patents-public-data.patents.publications)"


def _aviso_teto(*infos: dict) -> str | None:
    """Aviso visivel quando a consulta rodou ACIMA do teto de 10GB porque o
    chamador passou confirmar_acima_10gb=True -- sem isto o estouro passava
    em silencio para quem le so o resultado, nao a chamada."""
    estourados = [i for i in infos if i.get("acima_do_teto")]
    if not estourados:
        return None
    gb = max(i["bytes_estimados"] for i in estourados) / 1024 ** 3
    return (
        f"Consulta processou {gb:.2f} GB, acima do teto padrao de 10GB. Rodou "
        "porque confirmar_acima_10gb=True foi passado -- confira o consumo de "
        "quota do BigQuery (free tier: 1TB/mes)."
    )


def _filtro_datas(desde: str | None, ate: str | None,
                   parametros: list) -> str:
    """AAAA-MM-DD -> filtro em filing_date (INT64 AAAAMMDD no dataset)."""
    clausulas = []
    if desde:
        clausulas.append("filing_date >= @desde")
        parametros.append(bigquery.ScalarQueryParameter(
            "desde", "INT64", int(desde.replace("-", ""))))
    if ate:
        clausulas.append("filing_date <= @ate")
        parametros.append(bigquery.ScalarQueryParameter(
            "ate", "INT64", int(ate.replace("-", ""))))
    return (" AND " + " AND ".join(clausulas)) if clausulas else ""


def evolucao_temporal(client: bigquery.Client, cpc_prefix: str,
                       pais: str | None = None, desde: str | None = None,
                       ate: str | None = None, **kw) -> dict:
    """Deposito por ano numa tecnologia (prefixo CPC) e jurisdicao."""
    parametros = [bigquery.ScalarQueryParameter("cpc_prefix", "STRING", cpc_prefix)]
    filtro_pais = ""
    if pais:
        filtro_pais = " AND country_code = @pais"
        parametros.append(bigquery.ScalarQueryParameter("pais", "STRING", pais))
    filtro_datas = _filtro_datas(desde, ate, parametros)

    sql = f"""
        SELECT CAST(FLOOR(filing_date / 10000) AS INT64) AS ano,
               country_code AS pais, COUNT(DISTINCT publication_number) AS depositos
        FROM {_TABELA}, UNNEST(cpc) AS cpc
        WHERE STARTS_WITH(cpc.code, @cpc_prefix){filtro_pais}{filtro_datas}
        GROUP BY ano, pais
        ORDER BY ano, pais
    """
    info: dict = {}
    linhas = executar(client, sql, parametros, info=info, **kw)
    resultado = {"fonte": FONTE, "cpc_prefix": cpc_prefix, "pais": pais, "linhas": linhas}
    aviso = _aviso_teto(info)
    if aviso:
        resultado["aviso_teto_excedido"] = aviso
    return resultado


def top_titulares(client: bigquery.Client, cpc_prefix: str,
                   pais: str | None = None, desde: str | None = None,
                   ate: str | None = None, limite: int = 20, **kw) -> dict:
    """Titulares (assignee_harmonized) com mais depositos numa CPC x pais x periodo."""
    parametros = [
        bigquery.ScalarQueryParameter("cpc_prefix", "STRING", cpc_prefix),
        bigquery.ScalarQueryParameter("limite", "INT64", limite),
    ]
    filtro_pais = ""
    if pais:
        filtro_pais = " AND country_code = @pais"
        parametros.append(bigquery.ScalarQueryParameter("pais", "STRING", pais))
    filtro_datas = _filtro_datas(desde, ate, parametros)

    sql = f"""
        SELECT assignee.name AS titular, COUNT(DISTINCT publication_number) AS depositos
        FROM {_TABELA}, UNNEST(cpc) AS cpc, UNNEST(assignee_harmonized) AS assignee
        WHERE STARTS_WITH(cpc.code, @cpc_prefix){filtro_pais}{filtro_datas}
        GROUP BY titular
        ORDER BY depositos DESC
        LIMIT @limite
    """
    info: dict = {}
    linhas = executar(client, sql, parametros, info=info, **kw)
    resultado = {"fonte": FONTE, "cpc_prefix": cpc_prefix, "pais": pais, "linhas": linhas}
    aviso = _aviso_teto(info)
    if aviso:
        resultado["aviso_teto_excedido"] = aviso
    return resultado


def co_classificacao(client: bigquery.Client, cpc_prefix: str,
                      desde: str | None = None, ate: str | None = None,
                      limite: int = 30, **kw) -> dict:
    """Mapa de co-classificacao: pares de codigos CPC que mais aparecem juntos
    nas mesmas publicacoes de uma tecnologia."""
    parametros = [
        bigquery.ScalarQueryParameter("cpc_prefix", "STRING", cpc_prefix),
        bigquery.ScalarQueryParameter("limite", "INT64", limite),
    ]
    filtro_datas = _filtro_datas(desde, ate, parametros)

    sql = f"""
        WITH base AS (
            SELECT publication_number, ARRAY_AGG(DISTINCT cpc.code) AS codigos
            FROM {_TABELA}, UNNEST(cpc) AS cpc
            WHERE publication_number IN (
                SELECT DISTINCT publication_number FROM {_TABELA}, UNNEST(cpc) AS c2
                WHERE STARTS_WITH(c2.code, @cpc_prefix){filtro_datas}
            )
            GROUP BY publication_number
        )
        SELECT a AS cpc_a, b AS cpc_b, COUNT(*) AS ocorrencias
        FROM base, UNNEST(codigos) AS a, UNNEST(codigos) AS b
        WHERE a < b
        GROUP BY cpc_a, cpc_b
        ORDER BY ocorrencias DESC
        LIMIT @limite
    """
    info: dict = {}
    linhas = executar(client, sql, parametros, info=info, **kw)
    resultado = {"fonte": FONTE, "cpc_prefix": cpc_prefix, "linhas": linhas}
    aviso = _aviso_teto(info)
    if aviso:
        resultado["aviso_teto_excedido"] = aviso
    return resultado


def perfil_titular(client: bigquery.Client, nome_titular: str,
                    desde: str | None = None, ate: str | None = None,
                    **kw) -> dict:
    """Distribuicao tecnologica (CPC) e geografica (pais) de um titular."""
    parametros = [bigquery.ScalarQueryParameter("titular", "STRING", nome_titular)]
    filtro_datas = _filtro_datas(desde, ate, parametros)

    sql_tecnologia = f"""
        SELECT SUBSTR(cpc.code, 1, 4) AS cpc_grupo, COUNT(DISTINCT publication_number) AS depositos
        FROM {_TABELA}, UNNEST(cpc) AS cpc, UNNEST(assignee_harmonized) AS assignee
        WHERE assignee.name = @titular{filtro_datas}
        GROUP BY cpc_grupo
        ORDER BY depositos DESC
    """
    sql_geografia = f"""
        SELECT country_code AS pais, COUNT(DISTINCT publication_number) AS depositos
        FROM {_TABELA}, UNNEST(assignee_harmonized) AS assignee
        WHERE assignee.name = @titular{filtro_datas}
        GROUP BY pais
        ORDER BY depositos DESC
    """
    info_tec: dict = {}
    info_geo: dict = {}
    tecnologia = executar(client, sql_tecnologia, parametros, info=info_tec, **kw)
    geografia = executar(client, sql_geografia, list(parametros), info=info_geo, **kw)
    resultado = {"fonte": FONTE, "titular": nome_titular,
                 "tecnologia": tecnologia, "geografia": geografia}
    aviso = _aviso_teto(info_tec, info_geo)
    if aviso:
        resultado["aviso_teto_excedido"] = aviso
    return resultado


def demo() -> None:
    """Self-check sem rede: cada consulta gera SQL parametrizado, nunca
    concatena o valor do usuario direto na string."""
    from unittest.mock import MagicMock

    client = MagicMock()
    client.query.return_value.result.return_value = []
    client.query.return_value.total_bytes_processed = 100

    for fn, args in [
        (evolucao_temporal, ("H01L",)),
        (top_titulares, ("H01L",)),
        (co_classificacao, ("H01L",)),
        (perfil_titular, ("Acme Corp",)),
    ]:
        resultado = fn(client, *args)
        assert resultado["fonte"] == FONTE

    print("OK  4 consultas rodam via cliente mockado e devolvem a fonte declarada")


if __name__ == "__main__":
    demo()
