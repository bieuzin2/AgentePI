"""Servidor MCP para o EPO Open Patent Services v3.2.

Wrapper fino sobre ip-tools/python-epo-ops-client (Apache2, v4.2.2), que ja resolve
OAuth, throttling e retry. Este arquivo so traduz para MCP e achata a resposta.

Por que existe: o PPUBS do USPTO so ve os EUA. O EPO OPS indexa DOCDB/INPADOC, que
cobre BR, CN, EP e mais de 100 jurisdicoes. E a rota mais barata para cobertura global.

Credenciais em .env (nunca no codigo):  EPO_OPS_KEY, EPO_OPS_SECRET
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

import epo_ops
from epo_ops.middlewares import Throttler

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Teto duro da API do EPO. Pedir alem disso devolve erro, nunca resultado truncado
# em silencio -- busca de anterioridade que perde documento sem avisar e pior que
# busca que falha.
MAX_RESULTADOS = 2000
QUOTA_LOG = ROOT / "inpi" / "data" / "epo_quota.log"

mcp = FastMCP("epo-ops")

_client: epo_ops.Client | None = None


def cliente() -> epo_ops.Client:
    """Cliente EPO OPS. Levanta erro claro se as credenciais nao estiverem no .env."""
    global _client
    if _client is None:
        key, secret = os.getenv("EPO_OPS_KEY"), os.getenv("EPO_OPS_SECRET")
        if not key or not secret:
            raise RuntimeError(
                "EPO_OPS_KEY e/ou EPO_OPS_SECRET ausentes no .env. "
                "Registre um app em https://developers.epo.org (gratis, 4 GB/semana)."
            )
        _client = epo_ops.Client(
            key=key, secret=secret, accept_type="json", middlewares=[Throttler()]
        )
    return _client


def _loga_quota(op: str, resp) -> None:
    """Registra bytes consumidos. O free tier do EPO e 4 GB/semana e nao ha
    contador na API -- sem este log o teto so aparece quando ja foi estourado."""
    QUOTA_LOG.parent.mkdir(parents=True, exist_ok=True)
    with QUOTA_LOG.open("a", encoding="utf-8") as fh:
        fh.write(
            f"{datetime.now(timezone.utc).isoformat()}\t{op}\t{len(resp.content)}\n"
        )


def _texto(no: Any) -> str:
    """O JSON do EPO empacota texto em {'$': 'valor'} e repete campos como lista.
    Achata para string, que e o que o modelo consegue citar."""
    if no is None:
        return ""
    if isinstance(no, str):
        return no
    if isinstance(no, dict):
        return _texto(no.get("$", "")) or _texto(no.get("text", ""))
    if isinstance(no, list):
        return "; ".join(p for p in (_texto(x) for x in no) if p)
    return str(no)


def _lista(no: Any) -> list:
    """EPO devolve 1 item como dict e N itens como lista. Normaliza para lista."""
    if no is None:
        return []
    return no if isinstance(no, list) else [no]


def _ref(doc_id: Any) -> str:
    """Monta o identificador legivel (ex.: BR-102019000000-A2) a partir do
    document-id do DOCDB."""
    for d in _lista(doc_id):
        if not isinstance(d, dict):
            continue
        pais = _texto(d.get("country"))
        num = _texto(d.get("doc-number"))
        tipo = _texto(d.get("kind"))
        if num:
            return "-".join(p for p in (pais, num, tipo) if p)
    return ""


def _resumo_documento(ex: dict) -> dict:
    """Extrai so os campos de triagem de um exchange-document.

    Deliberadamente NAO devolve o documento inteiro: 10 documentos completos
    estouram a janela de contexto, e para triagem bastam titulo, data, titular e
    classificacao. O texto integral vem depois, por documento, sob demanda.
    """
    bib = ex.get("bibliographic-data", {}) if isinstance(ex, dict) else {}
    partes = bib.get("publication-reference", {}).get("document-id")

    titulos = {
        _texto(t.get("@lang")) or "??": _texto(t)
        for t in _lista(bib.get("invention-title"))
        if isinstance(t, dict)
    }
    titulares = [
        _texto(p.get("name"))
        for p in _lista(bib.get("parties", {}).get("applicants", {}).get("applicant"))
        if isinstance(p, dict)
    ]
    ipc = [
        _texto(c.get("text"))
        for c in _lista(
            bib.get("classifications-ipcr", {}).get("classification-ipcr")
        )
        if isinstance(c, dict)
    ]
    return {
        "referencia": _ref(partes),
        "pais": _texto(ex.get("@country")),
        "titulo": titulos.get("en") or (next(iter(titulos.values()), "")),
        "titulos_por_idioma": titulos,
        "data_publicacao": _texto(
            next(
                (
                    d.get("date")
                    for d in _lista(partes)
                    if isinstance(d, dict) and d.get("date")
                ),
                None,
            )
        ),
        "titulares": [t for t in dict.fromkeys(titulares) if t],
        "ipc": [c for c in dict.fromkeys(ipc) if c],
    }


def _entrada(referencia: str, formato: str):
    """Epodoc ('BR102019000000A2') ou Docdb ('BR.102019000000.A2')."""
    if formato == "docdb":
        partes = referencia.split(".")
        if len(partes) != 3:
            raise ValueError(
                "formato docdb exige 'PAIS.NUMERO.TIPO' (ex.: 'BR.102019000000.A2')"
            )
        pais, numero, tipo = partes
        return epo_ops.models.Docdb(numero, pais, tipo)
    return epo_ops.models.Epodoc(referencia)


@mcp.tool()
def epo_busca(cql: str, inicio: int = 1, fim: int = 25) -> dict:
    """Busca no DOCDB/INPADOC via CQL. Cobre BR, CN, EP e +100 jurisdicoes.

    USE QUANDO: a pergunta envolver Brasil, China, Europa ou qualquer pais fora
    dos EUA. O PPUBS do USPTO nao cobre nada disso.

    Sintaxe CQL do EPO (diferente da BRS do PPUBS -- nao misture):
      ti="biodegradable packaging"        titulo
      ab=biodegradable and ab=packaging   resumo
      ta=...                              titulo ou resumo
      pa="Braskem"                        titular
      in="Silva"                          inventor
      ipc=/low B65D65/46                  classificacao IPC
      pn=BR102019000000                   numero de publicacao
      pd within "2020 2026"               janela de data
      Combine com and / or / not.

    Args:
        cql: expressao CQL.
        inicio: primeiro resultado (1-based).
        fim: ultimo resultado. Teto duro da API do EPO: 2000.

    Returns:
        total: total de documentos que a consulta casou no acervo (numero real,
        nao o tamanho da pagina). resultados: campos de triagem por documento.
    """
    if fim > MAX_RESULTADOS:
        return {
            "erro": True,
            "mensagem": (
                f"O EPO OPS limita a {MAX_RESULTADOS} resultados por consulta; "
                f"foi pedido ate {fim}. Refine a CQL (adicione classificacao IPC ou "
                "janela de data) em vez de paginar alem do teto."
            ),
        }
    if inicio < 1 or fim < inicio:
        return {"erro": True, "mensagem": "Faixa invalida: exige 1 <= inicio <= fim."}

    resp = cliente().published_data_search(cql=cql, range_begin=inicio, range_end=fim)
    _loga_quota("busca", resp)

    corpo = resp.json().get("ops:world-patent-data", {})
    resultado = corpo.get("ops:biblio-search", {})
    total = int(_texto(resultado.get("@total-result-count")) or 0)
    docs = _lista(
        resultado.get("ops:search-result", {}).get("ops:publication-reference")
    )

    referencias = [_ref(d.get("document-id")) for d in docs if isinstance(d, dict)]
    saida = {
        "cql": cql,
        "total": total,
        "faixa": [inicio, fim],
        "resultados": [r for r in referencias if r],
    }
    if total > MAX_RESULTADOS:
        saida["aviso"] = (
            f"A consulta casou {total} documentos, acima do teto de {MAX_RESULTADOS} "
            "que a API entrega. Os resultados abaixo sao uma amostra, NAO o acervo "
            "completo -- refine a CQL antes de concluir qualquer coisa sobre novidade."
        )
    return saida


@mcp.tool()
def epo_biblio(referencia: str, formato: str = "epodoc") -> dict:
    """Dados bibliograficos de um documento: titulo, data, titulares, IPC.

    USE QUANDO: precisar confirmar titulo/data/titular de um numero que ja apareceu
    numa busca. Para o confronto elemento a elemento, use epo_texto_integral.

    Args:
        referencia: 'BR102019000000A2' (epodoc) ou 'BR.102019000000.A2' (docdb).
        formato: 'epodoc' (padrao) ou 'docdb'.
    """
    resp = cliente().published_data(
        reference_type="publication", input=_entrada(referencia, formato), endpoint="biblio"
    )
    _loga_quota("biblio", resp)
    corpo = resp.json().get("ops:world-patent-data", {})
    docs = _lista(corpo.get("exchange-documents", {}).get("exchange-document"))
    return {
        "referencia_consultada": referencia,
        "documentos": [_resumo_documento(d) for d in docs if isinstance(d, dict)],
    }


@mcp.tool()
def epo_familia_inpadoc(referencia: str, formato: str = "epodoc") -> dict:
    """Familia INPADOC: todos os membros do mesmo pedido nas demais jurisdicoes.

    USE QUANDO: (a) souber o numero em um pais e precisar do equivalente em outro
    -- tipicamente achar o BR a partir do US, ou o contrario; (b) mapear onde um
    concorrente protegeu a mesma invencao.

    Vale para novidade: membros da mesma familia sao a MESMA invencao. Nao os
    conte como anterioridades independentes num claim chart.
    """
    resp = cliente().family(
        reference_type="publication", input=_entrada(referencia, formato)
    )
    _loga_quota("familia", resp)
    corpo = resp.json().get("ops:world-patent-data", {})
    membros = _lista(
        corpo.get("ops:patent-family", {}).get("ops:family-member")
    )

    saida = []
    for m in membros:
        if not isinstance(m, dict):
            continue
        pub = m.get("publication-reference", {}).get("document-id")
        ref = _ref(pub)
        if ref:
            saida.append({"referencia": ref, "pais": ref.split("-")[0]})

    return {
        "referencia_consultada": referencia,
        "total_membros": len(saida),
        "paises": sorted({m["pais"] for m in saida}),
        "membros": saida,
    }


@mcp.tool()
def epo_texto_integral(referencia: str, secao: str = "claims", formato: str = "epodoc") -> dict:
    """Texto integral por secao: reivindicacoes, descricao ou resumo.

    USE QUANDO: for confrontar elemento a elemento. Peca 'claims' primeiro -- as
    reivindicacoes sao 2-5% do documento e definem o escopo; a descricao inteira
    raramente compensa o custo de contexto.

    LIMITE IMPORTANTE: o EPO OPS so tem texto integral de EP e WO (e poucos
    outros). Para BR, US e CN normalmente NAO ha. Se vier vazio, isso significa
    'o EPO nao tem o texto', nao 'o documento nao diz nada' -- e proibido concluir
    ausencia de revelacao a partir desta ferramenta.

    Args:
        secao: 'claims', 'description' ou 'abstract'.
    """
    if secao not in {"claims", "description", "abstract"}:
        return {
            "erro": True,
            "mensagem": "secao deve ser 'claims', 'description' ou 'abstract'.",
        }

    endpoint = "biblio" if secao == "abstract" else secao
    try:
        resp = cliente().published_data(
            reference_type="publication",
            input=_entrada(referencia, formato),
            endpoint=endpoint,
        )
    except Exception as e:  # 404 = sem texto integral nessa jurisdicao
        return {
            "referencia": referencia,
            "secao": secao,
            "texto": "",
            "disponivel": False,
            "mensagem": (
                f"O EPO OPS nao devolveu '{secao}' para {referencia} ({e}). "
                "Texto integral existe basicamente para EP e WO. Ausencia aqui NAO "
                "e evidencia de que o documento nao revela o elemento -- busque o "
                "texto na base nacional antes de marcar NAO LOCALIZADO."
            ),
        }

    _loga_quota(f"texto:{secao}", resp)
    corpo = resp.json().get("ops:world-patent-data", {})
    bruto = json.dumps(corpo, ensure_ascii=False)

    if secao == "claims":
        docs = _lista(corpo.get("ftxt:fulltext-documents", {}).get("ftxt:fulltext-document"))
        partes = [
            _texto(c.get("claim-text"))
            for d in docs
            if isinstance(d, dict)
            for c in _lista(d.get("claims", {}).get("claim"))
            if isinstance(c, dict)
        ]
        texto = "\n\n".join(p for p in partes if p)
    else:
        texto = ""

    return {
        "referencia": referencia,
        "secao": secao,
        "disponivel": bool(texto),
        "texto": texto,
        # Escape hatch: quando o achatamento nao pegar tudo, o bruto continua la.
        "bruto_json": bruto if not texto else None,
    }


if __name__ == "__main__":
    mcp.run()
