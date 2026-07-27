"""Levanta a familia INPADOC dos casos BR de um cliente, para montar o quadro global.

Serve para responder "quais anuidades esse cliente paga, no Brasil e fora".
O Brasil vem do INPI (completo e confiavel). O exterior vem da familia INPADOC do
EPO, que e onde estao os equivalentes.

⚠️ O QUE ESTE MODULO NAO FAZ: projetar data de anuidade estrangeira. As regras de
outras jurisdicoes estao em referencias/anuidades-por-jurisdicao.csv marcadas como
NAO-REVISADO -- sao transcricao de legislacao, sem verificacao contra dado e sem
revisao de profissional habilitado. Ele devolve o caso, o pais, a data de deposito e
a REGRA aplicavel, para o associado local confirmar a data.

Cache em disco: a mesma familia nao e buscada duas vezes. A cota do EPO e 4 GB por
semana e nao ha contador na API.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
load_dotenv(RAIZ.parent / ".env")

CACHE = RAIZ / "data" / "cache_familia"
QUOTA = RAIZ / "data" / "epo_quota.log"


def _cliente():
    import epo_ops
    from epo_ops.middlewares import Throttler

    return epo_ops.Client(
        key=os.getenv("EPO_OPS_KEY"), secret=os.getenv("EPO_OPS_SECRET"),
        accept_type="json", middlewares=[Throttler()],
    )


def _L(x):
    return x if isinstance(x, list) else ([] if x is None else [x])


def _txt(no):
    if isinstance(no, dict):
        return str(no.get("$", ""))
    return "" if no is None else str(no)


def familia(numero_br: str, cli=None) -> dict:
    """Familia INPADOC de um processo BR, com biblio de cada membro. Cacheado."""
    import epo_ops

    CACHE.mkdir(parents=True, exist_ok=True)
    arq = CACHE / f"{numero_br}.json"
    if arq.exists():
        return json.loads(arq.read_text(encoding="utf-8"))

    cli = cli or _cliente()
    try:
        r = cli.family(
            "publication", epo_ops.models.Epodoc(f"BR{numero_br}"),
            constituents=["biblio"],
        )
    except Exception as e:
        d = {"numero_br": numero_br, "erro": str(e)[:120], "membros": []}
        arq.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return d

    QUOTA.parent.mkdir(parents=True, exist_ok=True)
    with QUOTA.open("a", encoding="utf-8") as fh:
        fh.write(f"{time.time():.0f}\tfamilia:{numero_br}\t{len(r.content)}\n")

    fam = r.json()["ops:world-patent-data"]["ops:patent-family"]
    membros = []
    for mb in _L(fam.get("ops:family-member")):
        pub = _L(mb.get("publication-reference", {}).get("document-id"))
        docdb = next(
            (d for d in pub if d.get("@document-id-type") == "docdb"), None
        )
        if not docdb:
            continue
        pais = _txt(docdb.get("country"))
        num = _txt(docdb.get("doc-number"))
        kind = _txt(docdb.get("kind"))
        # data DA PUBLICACAO deste membro. Quando o kind e de concessao (B*/C*),
        # esta e a data de concessao -- que e a data-base da anuidade em US, JP,
        # KR e outros. Sem ela, esses paises ficavam sem estimativa possivel.
        pub_data = _txt(docdb.get("date")) or None
        # data de deposito vem da application-reference, nao da publicacao
        app = _L(mb.get("application-reference", {}).get("document-id"))
        dep = next((_txt(a.get("date")) for a in app if a.get("date")), None)
        # numero do PEDIDO: e o que casa o A1 com o B2 do mesmo caso, ja que nos
        # EUA a publicacao do pedido e a da patente tem numeros diferentes.
        app_num = next(
            (_txt(a.get("doc-number")) for a in app
             if a.get("@document-id-type") == "docdb" and a.get("doc-number")),
            None,
        )
        titulo = ""
        ex = mb.get("exchange-document")
        if isinstance(ex, dict):
            bib = ex.get("bibliographic-data", {})
            ts = _L(bib.get("invention-title"))
            en = next((t for t in ts if isinstance(t, dict)
                       and t.get("@lang") == "en"), None)
            titulo = _txt(en or (ts[0] if ts else ""))
        membros.append({
            "pais": pais,
            "referencia": "-".join(p for p in (pais, num, kind) if p),
            "numero": num,
            "kind": kind,
            "data_deposito": dep,
            "data_publicacao": pub_data,
            "numero_pedido": app_num,
            "concedida": bool(kind and kind[0] in ("B", "C")),
            "titulo": titulo,
        })

    d = {"numero_br": numero_br, "membros": membros,
         "familia_id": fam.get("@family-id")}
    arq.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


def levantar(numeros_br: list[str], pausa: float = 0.0) -> dict:
    """Levanta a familia de varios processos. Idempotente pelo cache."""
    cli = _cliente()
    saida, erros = {}, []
    for i, n in enumerate(numeros_br, 1):
        d = familia(n, cli)
        if d.get("erro"):
            erros.append((n, d["erro"]))
        saida[n] = d
        if pausa:
            time.sleep(pausa)
        print(f"  [{i}/{len(numeros_br)}] {n}: {len(d['membros'])} membros", flush=True)
    return {"familias": saida, "erros": erros}
