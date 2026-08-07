"""Panorama de topico livre + pais via EPO OPS (Fase H).

Fecha o gap achado em producao: perguntas tipo "quantas patentes de covid
foram depositadas no Nepal" nao tem classificacao CPC limpa, entao as tools
`landscape_*` (BigQuery, filtram por prefixo CPC) so conseguem responder
varrendo a base inteira -- uma consulta real estourou ~64GB. A rota barata ja
existia: `epo_busca` (CQL) devolve o total real do acervo DOCDB/INPADOC
(100+ jurisdicoes) e, com o constituent 'biblio', cada resultado ja vem com
titulo/titulares/inventores/IPC -- da para montar um panorama numa chamada so.

TRADUCAO: o usuario pergunta em PT-BR, a CQL do EPO precisa de termos em
ingles. Quem traduz e QUEM CHAMA esta tool (o modelo do agente) -- ela recebe
`termos_ingles` ja pronto, nunca traduz sozinha (evitaria depender de outra
chamada de rede so pra isso).
"""

from __future__ import annotations

from epo.epo_mcp import _lista, _loga_quota, _resumo_documento, _sem_resultado, _texto, cliente
from epo.mcp_app import mcp

AMOSTRA_MAXIMA = 500  # teto de itens por chamada com constituent=biblio (custa mais que so referencia)


def _monta_cql(termos_ingles: str, pais: str | None, desde: str | None, ate: str | None) -> str:
    clausulas = [f"ta=({termos_ingles.strip()})"]
    if pais:
        clausulas.append(f"pn={pais.strip().upper()}")
    if desde and ate:
        clausulas.append(f'pd within "{desde.replace("-", "")} {ate.replace("-", "")}"')
    return " and ".join(clausulas)


def _documentos(corpo: dict) -> list[dict]:
    """Acha todo exchange-document na resposta, em qualquer profundidade.

    Com constituents=['biblio'] o EPO aninha os documentos de forma que muda
    conforme o endpoint; caminhar a arvore procurando por 'bibliographic-data'
    e mais robusto que cravar o caminho exato."""
    achados: list[dict] = []

    def _anda(no):
        if isinstance(no, dict):
            if "bibliographic-data" in no:
                achados.append(no)
            for v in no.values():
                _anda(v)
        elif isinstance(no, list):
            for x in no:
                _anda(x)

    _anda(corpo)
    return achados


def _agrega(docs: list[dict]) -> dict:
    contagem_ipc: dict[str, int] = {}
    contagem_titular: dict[str, int] = {}
    contagem_pais: dict[str, int] = {}
    contagem_ano: dict[str, int] = {}
    titulares_distintos: set[str] = set()

    for d in docs:
        for subclasse in dict.fromkeys(c[:4] for c in d["ipc"] if len(c) >= 4):
            contagem_ipc[subclasse] = contagem_ipc.get(subclasse, 0) + 1
        for t in d["titulares"]:
            contagem_titular[t] = contagem_titular.get(t, 0) + 1
            titulares_distintos.add(t)
        if d["pais"]:
            contagem_pais[d["pais"]] = contagem_pais.get(d["pais"], 0) + 1
        if d["data_publicacao"] and len(d["data_publicacao"]) >= 4:
            ano = d["data_publicacao"][:4]
            contagem_ano[ano] = contagem_ano.get(ano, 0) + 1

    def _top(contagem: dict[str, int], limite: int = 10) -> list[dict]:
        chave_campo = "chave"
        return [
            {chave_campo: k, "documentos": v}
            for k, v in sorted(contagem.items(), key=lambda x: -x[1])[:limite]
        ]

    return {
        "top_ipc_subclasses": _top(contagem_ipc),
        "top_titulares": _top(contagem_titular),
        "distribuicao_por_pais": _top(contagem_pais, limite=30),
        "distribuicao_por_ano": sorted(
            ({"ano": a, "documentos": n} for a, n in contagem_ano.items()),
            key=lambda x: x["ano"],
        ),
        "titulares_distintos": len(titulares_distintos),
    }


@mcp.tool()
def epo_panorama_topico(termos_ingles: str, pais: str | None = None,
                         desde: str | None = None, ate: str | None = None,
                         amostra: int = 200) -> dict:
    """Panorama de um TOPICO LIVRE (nao uma classificacao CPC/IPC) num pais ou
    no mundo -- ex.: "quantas patentes relacionadas a covid foram depositadas
    no Nepal". Uma chamada so: total real do acervo + agregacoes (tecnologia,
    titulares, paises, anos) sobre uma amostra.

    USE QUANDO: a pergunta tiver um TEMA em palavras (nao um codigo CPC/IPC
    conhecido) e pedir contagem/panorama, com ou sem recorte de pais. NUNCA
    use landscape_* para topico livre -- landscape so filtra por prefixo CPC
    e sem um CPC limpo a consulta BigQuery varre a base inteira (ja gerou
    consulta de ~64GB em producao).

    TRADUCAO OBRIGATORIA: o usuario pergunta em PT-BR, mas a busca no EPO e
    em ingles. Traduza o topico ANTES de chamar, incluindo sinonimos uteis
    (ex.: covid -> 'covid OR coronavirus OR "sars-cov-2"'). Se o topico for
    ambiguo (pode ter mais de um sentido/sinonimo relevante), PERGUNTE ao
    usuario qual termo usar antes de chamar -- nao adivinhe e va direto.

    Args:
        termos_ingles: expressao de busca em ingles, pronta para virar
            'ta=(<isto>)' na CQL do EPO. Pode usar OR/AND/aspas.
        pais: codigo de 2 letras do pais de publicacao (ex.: 'NP' Nepal,
            'BR' Brasil). None = mundo todo.
        desde/ate: 'AAAA-MM-DD', filtro de data de publicacao (opcional).
        amostra: quantos documentos usar para as agregacoes (1 a 500). O
            'total' devolvido e sempre o do acervo inteiro, nao da amostra.

    Returns:
        total real do acervo, agregacoes sobre a amostra, e 'nota_amostra'
        quando total > amostra avisando que as distribuicoes sao aproximacao.
    """
    if not termos_ingles or not termos_ingles.strip():
        return {"erro": True, "mensagem": "termos_ingles nao pode ser vazio."}
    amostra = max(1, min(amostra, AMOSTRA_MAXIMA))

    cql = _monta_cql(termos_ingles, pais, desde, ate)

    try:
        resp = cliente().published_data_search(
            cql=cql, range_begin=1, range_end=amostra, constituents=["biblio"]
        )
    except Exception as e:
        if _sem_resultado(e):
            return {
                "cql_executada": cql, "total": 0, "titular": None,
                "top_ipc_subclasses": [], "top_titulares": [],
                "distribuicao_por_pais": [], "distribuicao_por_ano": [],
                "titulares_distintos": 0,
                "fonte": "EPO OPS (DOCDB), 100+ jurisdicoes",
                "nota": (
                    "Nenhum documento casou com esses termos/pais. Resultado "
                    "vazio e valido -- confira se o termo em ingles esta "
                    "certo antes de concluir ausencia."
                ),
            }
        raise
    _loga_quota("panorama_topico", resp)

    corpo = resp.json().get("ops:world-patent-data", {})
    busca = corpo.get("ops:biblio-search", {})
    total = int(_texto(busca.get("@total-result-count")) or 0)

    docs = [_resumo_documento(d) for d in _documentos(corpo)]

    resultado = {
        "cql_executada": cql,
        "total": total,
        **_agrega(docs),
        "fonte": "EPO OPS (DOCDB), 100+ jurisdicoes",
    }
    if total > len(docs):
        resultado["nota_amostra"] = (
            f"Agregacoes calculadas sobre {len(docs)} de {total} documentos "
            "no total (amostra). O 'total' e o numero real do acervo; as "
            "distribuicoes por tecnologia/titular/pais/ano sao aproximacao "
            "sobre a amostra, nao o universo completo."
        )
    return resultado


def demo() -> None:
    """Self-check sem rede: so a montagem de CQL e a agregacao."""
    assert _monta_cql("covid", "NP", None, None) == 'ta=(covid) and pn=NP'
    assert _monta_cql("covid", None, "2020-01-01", "2021-01-01") == (
        'ta=(covid) and pd within "20200101 20210101"'
    )
    docs = [
        {"ipc": ["A61K31/00"], "titulares": ["ACME"], "pais": "NP", "data_publicacao": "20200601"},
        {"ipc": ["A61K31/00"], "titulares": ["ACME"], "pais": "NP", "data_publicacao": "20210101"},
    ]
    agg = _agrega(docs)
    assert agg["top_ipc_subclasses"][0] == {"chave": "A61K", "documentos": 2}
    assert agg["titulares_distintos"] == 1
    print("OK  epo_panorama_topico: CQL e agregacao corretas (sem rede)")


if __name__ == "__main__":
    demo()
