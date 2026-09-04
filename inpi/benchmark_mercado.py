"""Compara a carteira de um escritorio contra o volume nacional agregado
(estatistica_nacional, Portal de Estatisticas do INPI) por campo tecnologico.

Depende de ipc_campo_tecnologico (inpi/ingest.py::_mescla_ipc_campo_tecnologico)
para cruzar o codigo IPC da carteira com o campo_tecnologico da taxonomia
WIPO-35 que estatistica_nacional usa -- sem essa tabela, so da pra comparar
por ano/decisao (sem quebra por area tecnica)."""

from __future__ import annotations

from inpi.consulta import _linhas, _tem_tabela
from inpi.mcp_app import mcp
from inpi.mercado import _chave_escritorio


@mcp.tool()
def inpi_benchmark_mercado(
    escritorio: str, ano_inicial: int | None = None, ano_final: int | None = None,
    campo_tecnologico: str | None = None,
) -> dict:
    """Compara a carteira de um escritorio com o volume NACIONAL agregado
    (Portal de Estatisticas do INPI) no mesmo campo tecnologico/periodo --
    share de mercado e volume absoluto lado a lado.

    USE QUANDO: perguntarem "que fatia do mercado farmaceutico nacional a
    carteira representa", "como a carteira cresce comparado ao pais" -- ou
    seja, comparativo carteira-vs-mercado, nao so ranking entre escritorios
    (para isso, use inpi_mercado).

    Args:
        escritorio: grafia de escritorio (resolvida pela chave canonica, como
            em inpi_carteira).
        ano_inicial/ano_final: filtro de ano de deposito (inclusive).
        campo_tecnologico: taxonomia WIPO-35 (ex.: 'Farmacêutica'). Sem
            ipc_campo_tecnologico carregada, ignorado -- resultado sai sem
            quebra por campo.
    """
    if not _tem_tabela("estatistica_nacional"):
        return {"erro": True, "mensagem": (
            "Tabela estatistica_nacional ausente -- rode "
            "inpi/estatistica_publica.py e depois inpi/ingest.py.")}

    tem_ipc_campo = _tem_tabela("ipc_campo_tecnologico")
    if campo_tecnologico and not tem_ipc_campo:
        return {"erro": True, "mensagem": (
            "Tabela ipc_campo_tecnologico ausente -- sem ela nao da pra filtrar "
            "por campo_tecnologico. Rode inpi/ingest.py apos carregar "
            "inpi/referencias/ipc-campo-tecnologico.csv.")}

    chave = _chave_escritorio(escritorio)

    cond_carteira, params_carteira = ["e.chave = ?"], [chave]
    if ano_inicial:
        cond_carteira.append("substr(b.data_deposito, 1, 4)::INTEGER >= ?")
        params_carteira.append(ano_inicial)
    if ano_final:
        cond_carteira.append("substr(b.data_deposito, 1, 4)::INTEGER <= ?")
        params_carteira.append(ano_final)
    join_campo = ""
    if campo_tecnologico:
        join_campo = " JOIN ipc_campo_tecnologico ct ON substr(i.simbolo, 1, 4) = ct.ipc_subclasse"
        cond_carteira.append("ct.campo_tecnologico = ?")
        params_carteira.append(campo_tecnologico)

    carteira = _linhas(
        f"""SELECT count(DISTINCT p.numero_inpi) AS depositos
            FROM procuradores p
            JOIN escritorios e ON e.original = p.procurador
            LEFT JOIN ipc i USING (numero_inpi)
            LEFT JOIN biblio b USING (numero_inpi)
            {join_campo}
            WHERE {' AND '.join(cond_carteira)}""",
        params_carteira,
    )[0]

    cond_nac, params_nac = [], []
    if ano_inicial:
        cond_nac.append("ano >= ?")
        params_nac.append(ano_inicial)
    if ano_final:
        cond_nac.append("ano <= ?")
        params_nac.append(ano_final)
    if campo_tecnologico:
        cond_nac.append("campo_tecnologico = ?")
        params_nac.append(campo_tecnologico)
    where_nac = ("WHERE " + " AND ".join(cond_nac)) if cond_nac else ""

    nacional = _linhas(
        f"SELECT sum(depositos) AS depositos, sum(concessoes) AS concessoes "
        f"FROM estatistica_nacional {where_nac}",
        params_nac,
    )[0]

    dep_carteira = carteira["depositos"] or 0
    dep_nacional = nacional["depositos"] or 0
    share = round(dep_carteira / dep_nacional * 100, 4) if dep_nacional else None

    return {
        "escritorio": escritorio,
        "chave": chave,
        "filtro": {"ano_inicial": ano_inicial, "ano_final": ano_final,
                   "campo_tecnologico": campo_tecnologico},
        "carteira": {"depositos": dep_carteira},
        "nacional": {"depositos": dep_nacional, "concessoes": nacional["concessoes"] or 0},
        "share_mercado_pct": share,
        "fonte_nacional": "Portal de Estatisticas do INPI (servicos.estatistica.inpi.gov.br)",
    }
