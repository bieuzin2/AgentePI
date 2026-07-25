"""Servidor MCP para o Lens.org (Patent API + Scholarly API).

Por que existe: EPO e USPTO cobrem documentos de patente. O que derruba novidade e
nao aparece em base de patente e a literatura NAO-PATENTARIA -- artigo, tese, anais de
congresso. O art. 11 da LPI e explicito: "por descricao escrita ou oral, por uso ou
qualquer outro meio". O Lens cruza ~166M patentes com ~200M publicacoes academicas.

ESTADO DE LICENCA: token de AVALIACAO. Os termos do Lens (v2026.06.01) vedam uso
comercial do output durante o trial. Toda resposta sai carimbada. Quando a assinatura
entrar, apague a constante CARIMBO e mais nada muda.

Credencial em .env: LENS_TOKEN. Sem ela o servidor nao sobe -- falha visivel.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BASE = "https://api.lens.org"
MAX_TAMANHO = 50  # teto por chamada; o objetivo aqui e triagem, nao dump

# Apague esta constante (e as duas linhas que a usam) quando a assinatura entrar.
CARIMBO = "[FONTE: Lens.org - token de avaliacao, uso interno]"

mcp = FastMCP("lens")


def _token() -> str:
    tok = os.getenv("LENS_TOKEN")
    if not tok:
        raise RuntimeError(
            "LENS_TOKEN ausente no .env. Solicite acesso em "
            "https://www.lens.org/lens/user/subscriptions#access"
        )
    return tok


def _post(caminho: str, corpo: dict) -> dict:
    r = httpx.post(
        f"{BASE}{caminho}",
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        json=corpo,
        timeout=90,
    )
    if r.status_code == 401:
        raise PermissionError(
            f"O Lens recusou o token para {caminho} (401). O token existe, mas nao "
            "cobre este produto -- Patent API e Scholarly API sao assinaturas "
            "separadas. Peca acesso ao produto que falta em "
            "https://www.lens.org/lens/user/subscriptions#access"
        )
    if r.status_code == 429:
        raise RuntimeError("Lens: limite de requisicoes atingido (429). Aguarde e repita.")
    r.raise_for_status()
    return r.json()


def _txt(v) -> str:
    if isinstance(v, dict):
        return str(v.get("value") or v.get("text") or "")
    return "" if v is None else str(v)


def _titulo(item: dict) -> str:
    """invention_title e lista de {text, lang}. Prefere ingles; cai no primeiro."""
    ts = item.get("biblio", {}).get("invention_title") or item.get("title")
    if isinstance(ts, str):
        return ts
    ts = ts or []
    if isinstance(ts, dict):
        ts = [ts]
    en = next((t for t in ts if isinstance(t, dict) and t.get("lang") == "en"), None)
    return _txt(en or (ts[0] if ts else ""))


@mcp.tool()
def lens_busca_npl(consulta: str, campo: str = "title", tamanho: int = 10) -> dict:
    """Busca LITERATURA NAO-PATENTARIA (artigo, tese, anais) na Scholarly API.

    USE QUANDO: for avaliar novidade sob o art. 11 da LPI. O estado da tecnica
    inclui "descricao escrita ou oral, por uso ou qualquer outro meio" -- e nao so
    documentos de patente. Um artigo publicado antes da data de deposito destroi
    novidade com a mesma forca de uma patente anterior, e nem EPO nem USPTO o
    indexam bem. Esta e a unica capacidade do Lens que EPO+USPTO nao cobrem.

    Args:
        consulta: termos de busca.
        campo: 'title', 'abstract', 'full_text' ou 'title_abstract'.
        tamanho: 1 a 50.
    """
    tamanho = max(1, min(tamanho, MAX_TAMANHO))
    d = _post(
        "/scholarly/search",
        {
            "query": {"match": {campo: consulta}},
            "size": tamanho,
            "include": [
                "lens_id", "title", "abstract", "year_published", "authors",
                "external_ids", "source", "publication_type",
            ],
        },
    )
    itens = []
    for it in d.get("data", []):
        autores = [
            " ".join(p for p in (a.get("first_name"), a.get("last_name")) if p)
            for a in (it.get("authors") or [])
            if isinstance(a, dict)
        ]
        dois = [
            e.get("value")
            for e in (it.get("external_ids") or [])
            if isinstance(e, dict) and e.get("type") == "doi"
        ]
        itens.append(
            {
                "lens_id": it.get("lens_id"),
                "titulo": _txt(it.get("title")),
                "ano": it.get("year_published"),
                "doi": dois[0] if dois else None,
                "autores": autores[:8],
                "publicacao": _txt((it.get("source") or {}).get("title")),
                "tipo": it.get("publication_type"),
                "resumo": (it.get("abstract") or "")[:600],
            }
        )
    return {
        "licenca": CARIMBO,
        "consulta": consulta,
        "campo": campo,
        "total": d.get("total"),
        "retornados": len(itens),
        "resultados": itens,
    }


@mcp.tool()
def lens_busca_patente(consulta: str, campo: str = "title", jurisdicao: str | None = None,
                       tamanho: int = 10) -> dict:
    """Busca patentes no acervo global do Lens (~166M documentos).

    USE QUANDO: quiser um terceiro angulo alem de PPUBS e EPO OPS -- o Lens indexa
    e normaliza de forma diferente e as vezes traz o que os outros dois nao trazem.
    NAO substitui o EPO: para familia INPADOC e dados oficiais, o EPO e a fonte.

    Args:
        consulta: termos de busca.
        campo: 'title', 'abstract', 'claim', 'description' ou 'full_text'.
        jurisdicao: sigla de 2 letras para filtrar (ex.: 'BR', 'CN', 'US').
        tamanho: 1 a 50.
    """
    tamanho = max(1, min(tamanho, MAX_TAMANHO))
    consulta_lens: dict = {"match": {campo: consulta}}
    if jurisdicao:
        consulta_lens = {
            "bool": {
                "must": [
                    {"match": {campo: consulta}},
                    {"term": {"jurisdiction": jurisdicao.upper()}},
                ]
            }
        }
    d = _post("/patent/search", {"query": consulta_lens, "size": tamanho})

    itens = []
    for it in d.get("data", []):
        bib = it.get("biblio", {})
        titulares = [
            _txt(a.get("extracted_name"))
            for a in (bib.get("parties", {}).get("applicants") or [])
            if isinstance(a, dict)
        ]
        juris, num, kind = it.get("jurisdiction"), it.get("doc_number"), it.get("kind")
        itens.append(
            {
                "referencia": "-".join(p for p in (juris, num, kind) if p),
                "jurisdicao": juris,
                "titulo": _titulo(it),
                "data_publicacao": it.get("date_published"),
                "titulares": [t for t in dict.fromkeys(titulares) if t],
                "familia_simples": (it.get("families", {}) or {})
                .get("simple_family", {})
                .get("size"),
                "lens_id": it.get("lens_id"),
                "resumo": _txt(
                    (it.get("abstract") or [{}])[0]
                    if isinstance(it.get("abstract"), list)
                    else it.get("abstract")
                )[:600],
            }
        )
    return {
        "licenca": CARIMBO,
        "consulta": consulta,
        "campo": campo,
        "jurisdicao": jurisdicao,
        "total": d.get("total"),
        "retornados": len(itens),
        "resultados": itens,
        "nota": (
            "Documentos aqui podem repetir o que PPUBS e EPO ja trouxeram. Antes de "
            "montar o quadro de confronto, agrupe por familia -- membros da mesma "
            "familia sao a MESMA invencao e contam como um documento na novidade."
        ),
    }


if __name__ == "__main__":
    mcp.run()
