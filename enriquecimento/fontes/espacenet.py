"""Espacenet (worldwide.espacenet.com): validação cruzada de citações -- NÃO é
fonte primária (essa é google_patents.py).

Verificado na Fase 0 de descoberta: a UI nova do Espacenet é uma SPA que fala
com uma API REST própria e pública, `/3.2/rest-services/...` (ex.:
`/3.2/rest-services/search/family/{familyId}/aggregated/biblio`), mas fica
atrás de um desafio Cloudflare (`cdn-cgi/challenge-platform`) -- daí o
intervalo mínimo de 5s neste host em enriquecimento/limitador.py, o mais
cauteloso dos três, e o motivo de esta fonte nunca bloquear o enriquecimento
(é validação, não requisito).

LIMITE DECLARADO: a aba "Citations" do Espacenet é renderizada por um bundle
JS próprio (`publication-viewer`) cujo endpoint JSON específico de citações
não foi confirmado na Fase 0 -- só o endpoint de biblio agregada. Esta função
busca a família via biblio (que resolve o family-id a partir do número
publicado) e devolve os documentos citantes/citados SE estiverem presentes
nesse payload; quando não estiverem, devolve ok=False com essa limitação
explícita, nunca uma lista vazia disfarçada de "sem citação"."""

from __future__ import annotations

from dataclasses import dataclass, field

from enriquecimento.limitador import requisitar

HOST = "worldwide.espacenet.com"
BASE = f"https://{HOST}/3.2/rest-services"


@dataclass
class ResultadoCitacoesEspacenet:
    ok: bool
    citacoes: list[dict] = field(default_factory=list)
    mensagem: str = ""


def _family_id(numero_epodoc: str) -> str | None:
    """Resolve o family-id a partir de uma busca simples -- o mesmo primeiro
    passo que o clique numa página de resultado do Espacenet dispara."""
    import json

    resp = requisitar(
        "post", f"{BASE}/search",
        host=HOST,
        params={"q": numero_epodoc, "qlang": "cql", "lang": "en,de,fr"},
    )
    if resp is None or resp.status_code != 200:
        return None
    try:
        corpo = json.loads(resp.text)
    except ValueError:
        return None
    resultados = (
        corpo.get("result", {})
        .get("exchange-documents", {})
        .get("exchange-document", [])
    )
    if isinstance(resultados, dict):
        resultados = [resultados]
    for doc in resultados:
        fam = doc.get("@family-id")
        if fam:
            return str(fam)
    return None


def validar_citacoes(numero_epodoc: str) -> ResultadoCitacoesEspacenet:
    """`numero_epodoc`: referência no formato aceito pela busca CQL do
    Espacenet (ex.: 'BR202022022566' ou 'US9876543'), tipicamente o mesmo
    `doc_id` já resolvido por outra fonte, sem kind code."""
    import json

    family_id = _family_id(numero_epodoc)
    if family_id is None:
        return ResultadoCitacoesEspacenet(
            ok=False,
            mensagem=f"{numero_epodoc}: não foi possível resolver family-id no Espacenet",
        )

    resp = requisitar(
        "get", f"{BASE}/search/family/{family_id}/aggregated/biblio",
        host=HOST, params={"q": numero_epodoc, "qlang": "cql", "lang": "en,de,fr"},
    )
    if resp is None or resp.status_code != 200:
        return ResultadoCitacoesEspacenet(
            ok=False,
            mensagem=f"family {family_id}: biblio agregada indisponível",
        )
    try:
        corpo = json.loads(resp.text)
    except ValueError:
        return ResultadoCitacoesEspacenet(
            ok=False, mensagem=f"family {family_id}: resposta não é JSON válido",
        )

    citacoes_bruto = _busca_chave(corpo, "citation")
    if not citacoes_bruto:
        return ResultadoCitacoesEspacenet(
            ok=False,
            mensagem=(
                "payload de biblio agregada não trouxe citações neste family-id "
                "-- endpoint específico de citações do Espacenet não confirmado "
                "na Fase 0 (ver docstring do módulo); use google_patents como "
                "fonte de citações."
            ),
        )
    return ResultadoCitacoesEspacenet(ok=True, citacoes=citacoes_bruto)


def _busca_chave(no, chave: str) -> list:
    """Procura recursivamente por uma chave em qualquer profundidade do JSON
    -- o payload do Espacenet aninha de forma irregular conforme o tipo de
    documento, igual ao OPS (ver _folhas em epo/epo_mcp.py)."""
    achados: list = []
    if isinstance(no, dict):
        for k, v in no.items():
            if chave in k.lower():
                achados.append(v)
            achados.extend(_busca_chave(v, chave))
    elif isinstance(no, list):
        for item in no:
            achados.extend(_busca_chave(item, chave))
    return achados
