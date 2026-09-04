"""Consulta o dataset agregado nacional do INPI (Portal de Estatisticas,
servicos.estatistica.inpi.gov.br) -- ano/tipo de ativo/campo tecnologico/
regiao/decisao, com depositos/concessoes/decisoes/vigencias.

Distinto de inpi_estatistica (soma/media sobre ledgers POR ESCRITORIO/titular
coletados do pePI, inpi/estatistica.py): este e dado NACIONAL agregado, sem
recorte por escritorio/titular, carregado pela tabela estatistica_nacional
(inpi/estatistica_publica.py + inpi/ingest.py)."""

from __future__ import annotations

from inpi.consulta import _linhas, _tem_tabela
from inpi.mcp_app import mcp

_FILTROS = {
    "ano_inicial": "ano >= ?",
    "ano_final": "ano <= ?",
    "tipo_ativo": "tipo_ativo = ?",
    "campo_tecnologico": "campo_tecnologico = ?",
    "regiao": "regiao = ?",
    "decisao": "decisao = ?",
}


@mcp.tool()
def inpi_estatistica_nacional(
    ano_inicial: int | None = None, ano_final: int | None = None,
    tipo_ativo: str | None = None, campo_tecnologico: str | None = None,
    regiao: str | None = None, decisao: str | None = None,
) -> dict:
    """Serie agregada nacional de depositos/concessoes por ano, do Portal de
    Estatisticas do INPI (dado publico, todo o pais -- NAO e por escritorio
    ou titular).

    USE QUANDO: a pergunta for sobre volume nacional/setorial (ex.: "quantos
    depositos de patente em Quimica em 2023", "concessoes por regiao"). Para
    o desempenho de UM escritorio/titular especifico, use inpi_mercado ou
    inpi_estatistica -- ferramentas diferentes, granularidade diferente.

    Args:
        ano_inicial/ano_final: filtro de ano de deposito (inclusive).
        tipo_ativo: 'Patentes', 'Marcas', 'Desenho Industrial', 'Contratos de
            Tecnologia', 'Programa de Computador', 'Topografia de CI'.
        campo_tecnologico: so relevante para Patentes (ex.: 'Quimica').
        regiao: regiao do titular/depositante.
        decisao: 'Concessao', 'Indeferimento', 'Arquivamento', etc.
    """
    if not _tem_tabela("estatistica_nacional"):
        return {"erro": True, "mensagem": (
            "Tabela estatistica_nacional ausente -- rode "
            "inpi/estatistica_publica.py e depois inpi/ingest.py.")}

    valores = {"ano_inicial": ano_inicial, "ano_final": ano_final,
              "tipo_ativo": tipo_ativo, "campo_tecnologico": campo_tecnologico,
              "regiao": regiao, "decisao": decisao}
    cond, params = [], []
    for chave, sql in _FILTROS.items():
        if valores[chave] is not None:
            cond.append(sql)
            params.append(valores[chave])
    where = ("WHERE " + " AND ".join(cond)) if cond else ""

    linhas = _linhas(
        f"""SELECT ano, sum(depositos) AS depositos, sum(concessoes) AS concessoes,
                   sum(n_decisoes) AS n_decisoes, sum(n_vigentes) AS n_vigentes
            FROM estatistica_nacional {where}
            GROUP BY ano ORDER BY ano""",
        params,
    )
    return {
        "filtros": {k: v for k, v in valores.items() if v is not None},
        "por_ano": linhas,
        "total_depositos": sum(r["depositos"] or 0 for r in linhas),
        "total_concessoes": sum(r["concessoes"] or 0 for r in linhas),
        "fonte": "Portal de Estatisticas do INPI (servicos.estatistica.inpi.gov.br) "
                 "-- dado agregado nacional publico, atualizado por coleta periodica "
                 "(nao e o dump semanal de dados abertos).",
    }
