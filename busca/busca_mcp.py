"""Servidor MCP 'busca': pipeline de anterioridade e busca de literatura cientifica (NPL).

So registra tools; a logica mora em busca/pipeline.py e busca/openalex.py.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from busca import openalex
from busca.pipeline import busca_anterioridade as _busca_anterioridade

mcp = FastMCP("busca")


@mcp.tool()
def busca_anterioridade(conceitos: list[str], ipc: list[str] | None = None,
                        desde: str | None = None, data_critica: str | None = None,
                        limite_por_fonte: int = 20) -> dict:
    """Busca de anterioridade em paralelo: INPI (texto+IPC) + EPO OPS (CQL) + OpenAlex (NPL).

    USE QUANDO: precisar levantar estado da tecnica para uma invencao. ANTES de
    chamar esta tool, decomponha a invencao em conceitos-chave e sinonimos usando a
    skill analista-patentes-inpi -- essa decomposicao e trabalho do modelo, nao
    desta ferramenta.

    O que faz: roda as consultas em paralelo, deduplica documentos de patente pela
    mesma familia INPADOC (reusa inpi/familia_epo.py e epo_familia_inpadoc) e devolve
    lista ranqueada por sobreposicao de conceitos e data. 'estrategia' documenta
    exatamente o que rodou, com quantos hits, e o que foi pulado -- confira antes de
    tratar a cobertura como completa.

    NAO retorna veredito de patenteabilidade. 'anterior_a_data_critica' e um fato
    objetivo de data, nao uma conclusao sobre novidade ou atividade inventiva.

    PPUBS (USPTO) NAO roda aqui -- ver 'estrategia.fontes_executadas.ppubs'. Use o
    servidor MCP 'uspto' (ppubs_search_patents) manualmente para cobertura US.

    Args:
        conceitos: conceitos-chave (e sinonimos) ja decompostos pela skill.
        ipc: classificacoes IPC opcionais para filtrar/complementar.
        desde: 'AAAA-MM-DD' opcional, filtra resultados a partir desta data.
        data_critica: 'AAAA-MM-DD' da invencao em exame, so para marcar datas
            anteriores/posteriores -- nunca para decidir novidade.
        limite_por_fonte: teto de resultados por consulta (1-50).
    """
    return _busca_anterioridade(conceitos, ipc=ipc, desde=desde,
                                data_critica=data_critica, limite_por_fonte=limite_por_fonte)


@mcp.tool()
def busca_npl(termos: str, desde: str | None = None, limite: int = 20) -> dict:
    """Busca literatura cientifica (NPL) no OpenAlex, sem chave e sem custo.

    USE QUANDO: precisar de anterioridade nao-patentaria (artigo, tese, ata de
    congresso) para uma invencao, isolado do restante do pipeline.

    Args:
        termos: texto livre de busca.
        desde: 'AAAA-MM-DD' opcional -- filtra por data de publicacao.
        limite: 1 a 100.
    """
    return openalex.buscar(termos, desde=desde, limite=limite)


if __name__ == "__main__":
    mcp.run()
