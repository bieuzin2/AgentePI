"""Cliente para api.openalex.org -- literatura cientifica (NPL) para anterioridade.

Sem chave, sem custo. Cache simples em disco (arquivo json por consulta): a mesma
busca nao bate na rede duas vezes, mesmo padrao de inpi/familia_epo.py.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent
CACHE = RAIZ / "data" / "cache_openalex"
BASE_URL = "https://api.openalex.org/works"
TTL_SEGUNDOS = 30 * 86400  # 30 dias -- literatura publicada nao muda; so entra achado novo


def _chave(termos: str, desde: str | None, limite: int) -> str:
    bruto = f"{termos.strip().lower()}|{desde or ''}|{limite}"
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:24]


def buscar(termos: str, desde: str | None = None, limite: int = 20) -> dict:
    """Busca trabalhos cientificos no OpenAlex por texto livre.

    Args:
        termos: texto de busca (titulo/resumo/texto integral indexado pelo OpenAlex).
        desde: opcional, 'AAAA-MM-DD' -- filtra por data de publicacao (from_publication_date).
        limite: 1 a 100.
    """
    termos = (termos or "").strip()
    if not termos:
        return {"erro": True, "mensagem": "Informe ao menos um termo de busca."}
    limite = max(1, min(limite, 100))

    CACHE.mkdir(parents=True, exist_ok=True)
    arq = CACHE / f"{_chave(termos, desde, limite)}.json"
    if arq.exists():
        d = json.loads(arq.read_text(encoding="utf-8"))
        if time.time() - d.get("consultado_em_ts", 0) < TTL_SEGUNDOS:
            return d["resposta"]

    params = {"search": termos, "per_page": limite}
    if desde:
        params["filter"] = f"from_publication_date:{desde}"

    try:
        r = httpx.get(BASE_URL, params=params, timeout=30,
                       headers={"User-Agent": "patentes-clarkemodet (busca de anterioridade)"})
        r.raise_for_status()
    except httpx.HTTPError as e:
        return {"erro": True, "mensagem": f"Falha ao consultar OpenAlex: {e}",
                "termos": termos, "resultados": []}

    corpo = r.json()
    resultados = []
    for w in corpo.get("results", []):
        resultados.append({
            "titulo": w.get("title") or "",
            "doi": w.get("doi"),
            "ano": w.get("publication_year"),
            "data_publicacao": w.get("publication_date"),
            "autores": [
                a.get("author", {}).get("display_name")
                for a in w.get("authorships", []) if a.get("author")
            ],
            "citado_por": w.get("cited_by_count"),
            "fonte": "openalex",
            "id_openalex": w.get("id"),
        })

    resposta = {
        "termos": termos,
        "desde": desde,
        "total": corpo.get("meta", {}).get("count", len(resultados)),
        "retornados": len(resultados),
        "resultados": resultados,
        "nota": (
            "Busca textual do OpenAlex, nao semantica. Cobre literatura cientifica "
            "(NPL), nao patentes -- use junto com INPI/EPO, nao no lugar deles."
        ),
    }
    arq.write_text(
        json.dumps({"consultado_em_ts": time.time(), "resposta": resposta}, ensure_ascii=False),
        encoding="utf-8",
    )
    return resposta
