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
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dogpile.cache import make_region
from dotenv import load_dotenv

import epo_ops
from epo_ops.middlewares import Dogpile, Throttler

from epo.mcp_app import mcp

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Teto duro da API do EPO. Pedir alem disso devolve erro, nunca resultado truncado
# em silencio -- busca de anterioridade que perde documento sem avisar e pior que
# busca que falha.
MAX_RESULTADOS = 2000
QUOTA_LOG = ROOT / "inpi" / "data" / "epo_quota.log"

# Cache local das respostas OPS (dogpile.cache, ja incluso no python-epo-ops-client).
# Poupa quota: familia INPADOC e status legal de um mesmo documento nao mudam de um
# dia para o outro. Duas semanas de TTL, mesmo padrao da lib.
CACHE_DBM = ROOT / "epo" / "data" / "cache.dbm"

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
        CACHE_DBM.parent.mkdir(parents=True, exist_ok=True)
        region = make_region().configure(
            "dogpile.cache.dbm",
            expiration_time=60 * 60 * 24 * 14,  # 2 semanas
            arguments={"filename": str(CACHE_DBM)},
        )
        _client = epo_ops.Client(
            key=key, secret=secret, accept_type="json",
            middlewares=[Dogpile(region=region), Throttler()],
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


# IPC no EPO vem em largura fixa do padrao WIPO:
# "B65D  65/    46            A I"  ->  "B65D65/46"
_RE_IPC = re.compile(r"([A-H])\s*(\d{1,2})\s*([A-Z])\s*(\d+)\s*/\s*(\d+)")


def _normaliza_ipc(bruto: str) -> str:
    m = _RE_IPC.search(bruto or "")
    if not m:
        return (bruto or "").strip()
    sec, cls, sub, grupo, subgrupo = m.groups()
    return f"{sec}{cls.zfill(2)}{sub}{grupo}/{subgrupo}"


def _partes(bloco: dict, papel: str) -> list[str]:
    """Extrai nomes de applicants/inventors.

    Duas armadilhas do EPO: (1) o nome fica em '<papel>-name'.'name', um nivel
    mais fundo do que parece; (2) cada parte aparece DUAS vezes, uma com
    @data-format='epodoc' (normalizado, com sufixo '[BR]') e outra 'original'
    (como foi depositado). Preferimos 'original' -- e o nome que o analista
    reconhece e o que casa com busca por titular.
    """
    itens = _lista(bloco.get(papel, {}).get(f"{papel[:-1]}"))
    por_formato: dict[str, list[str]] = {"original": [], "epodoc": []}
    for p in itens:
        if not isinstance(p, dict):
            continue
        nome = _texto(p.get(f"{papel[:-1]}-name", {}).get("name"))
        if not nome:
            continue
        fmt = p.get("@data-format", "epodoc")
        por_formato.setdefault(fmt, []).append(nome)
    escolhidos = por_formato.get("original") or por_formato.get("epodoc") or []
    return list(dict.fromkeys(escolhidos))


def _resumo_documento(ex: dict) -> dict:
    """Extrai so os campos de triagem de um exchange-document.

    Deliberadamente NAO devolve o documento inteiro: 10 documentos completos
    estouram a janela de contexto, e para triagem bastam titulo, data, titular e
    classificacao. O texto integral vem depois, por documento, sob demanda.
    """
    bib = ex.get("bibliographic-data", {}) if isinstance(ex, dict) else {}
    doc_id = bib.get("publication-reference", {}).get("document-id")

    titulos = {
        _texto(t.get("@lang")) or "??": _texto(t)
        for t in _lista(bib.get("invention-title"))
        if isinstance(t, dict)
    }
    bloco_partes = bib.get("parties") if isinstance(bib.get("parties"), dict) else {}
    titulares = _partes(bloco_partes, "applicants")
    inventores = _partes(bloco_partes, "inventors")
    ipc = [
        _normaliza_ipc(_texto(c.get("text")))
        for c in _lista(
            bib.get("classifications-ipcr", {}).get("classification-ipcr")
        )
        if isinstance(c, dict)
    ]
    return {
        "referencia": _ref(doc_id),
        "pais": _texto(ex.get("@country")),
        "titulo": titulos.get("en") or (next(iter(titulos.values()), "")),
        "titulos_por_idioma": titulos,
        "data_publicacao": _texto(
            next(
                (
                    d.get("date")
                    for d in _lista(doc_id)
                    if isinstance(d, dict) and d.get("date")
                ),
                None,
            )
        ),
        "titulares": titulares,
        "inventores": inventores,
        "ipc": [c for c in dict.fromkeys(ipc) if c],
    }


_RE_REF = re.compile(r"^([A-Z]{2})[-. ]?(\d+)[-. ]?([A-Z]\d?)?$", re.IGNORECASE)


def _entrada(referencia: str):
    """Converte qualquer forma usual de referencia no input que a API aceita.

    Aceita 'BR-102022010731-A2' (que e o que epo_busca devolve), 'BR102022010731A2',
    'BR102022010731' e 'BR.102022010731.A2'.

    Detalhe que custa 404 se ignorado: o formato **epodoc nao aceita kind code**.
    'BR102022010731A2' devolve 404; 'BR102022010731' devolve 200. Docdb aceita o kind
    e e inequivoco, entao e o preferido sempre que o kind for conhecido.
    """
    ref = (referencia or "").strip().upper()
    m = _RE_REF.match(ref)
    if not m:
        raise ValueError(
            f"Referencia '{referencia}' nao reconhecida. Use algo como "
            "'BR-102022010731-A2', 'BR102022010731' ou 'EP1000000'."
        )
    pais, numero, kind = m.group(1), m.group(2), m.group(3)
    if kind:
        return epo_ops.models.Docdb(numero, pais, kind)
    return epo_ops.models.Epodoc(f"{pais}{numero}")


def _sem_resultado(exc: Exception) -> bool:
    """O EPO devolve 404 tanto para 'nao existe' quanto para 'busca sem resultado'.
    Tratar como erro faz uma busca legitimamente vazia parecer falha de sistema."""
    return "404" in str(exc)


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

    try:
        resp = cliente().published_data_search(cql=cql, range_begin=inicio, range_end=fim)
    except Exception as e:
        if _sem_resultado(e):
            return {
                "cql": cql,
                "total": 0,
                "faixa": [inicio, fim],
                "resultados": [],
                "nota": (
                    "Nenhum documento casou com esta CQL. Resultado vazio e valido "
                    "e nao e falha de sistema. Antes de concluir ausencia de "
                    "anterioridade, tente por classificacao IPC, que independe de "
                    "vocabulario."
                ),
            }
        raise
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
def epo_biblio(referencia: str) -> dict:
    """Dados bibliograficos de um documento: titulo, data, titulares, IPC.

    USE QUANDO: precisar confirmar titulo/data/titular de um numero que ja apareceu
    numa busca. Para o confronto elemento a elemento, use epo_texto_integral.

    Args:
        referencia: aceita a forma que epo_busca devolve ('BR-102022010731-A2'),
            e tambem 'BR102022010731' ou 'EP1000000'.
    """
    try:
        resp = cliente().published_data(
            reference_type="publication", input=_entrada(referencia), endpoint="biblio"
        )
    except Exception as e:
        if _sem_resultado(e):
            return {
                "referencia_consultada": referencia,
                "documentos": [],
                "nota": "O EPO nao tem esse documento com essa referencia. Confira o numero.",
            }
        raise
    _loga_quota("biblio", resp)
    corpo = resp.json().get("ops:world-patent-data", {})
    docs = _lista(corpo.get("exchange-documents", {}).get("exchange-document"))
    return {
        "referencia_consultada": referencia,
        "documentos": [_resumo_documento(d) for d in docs if isinstance(d, dict)],
    }


@mcp.tool()
def epo_familia_inpadoc(referencia: str) -> dict:
    """Familia INPADOC: todos os membros do mesmo pedido nas demais jurisdicoes.

    USE QUANDO: (a) souber o numero em um pais e precisar do equivalente em outro
    -- tipicamente achar o BR a partir do US, ou o contrario; (b) mapear onde um
    concorrente protegeu a mesma invencao.

    Vale para novidade: membros da mesma familia sao a MESMA invencao. Nao os
    conte como anterioridades independentes num claim chart.
    """
    try:
        resp = cliente().family(
            reference_type="publication", input=_entrada(referencia)
        )
    except Exception as e:
        if _sem_resultado(e):
            return {
                "referencia_consultada": referencia,
                "total_membros": 0,
                "paises": [],
                "membros": [],
                "nota": "O EPO nao tem familia INPADOC para essa referencia.",
            }
        raise
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
def epo_texto_integral(referencia: str, secao: str = "claims") -> dict:
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
            input=_entrada(referencia),
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
    elif secao == "description":
        # Mesma arvore das reivindicacoes, outro no. A descricao vem em <p>
        # numerados -- que sao justamente a localizacao que a ancora tripla exige
        # ('[0034]'), entao juntar por paragrafo, nunca por '; '.
        docs = _lista(corpo.get("ftxt:fulltext-documents", {}).get("ftxt:fulltext-document"))
        partes = []
        for d in docs:
            if not isinstance(d, dict):
                continue
            desc = d.get("description")
            if isinstance(desc, dict) and desc.get("p") is not None:
                partes.extend(_texto(p) for p in _lista(desc["p"]))
            else:
                partes.append(_texto(desc))
        texto = "\n\n".join(p for p in partes if p)
    else:
        # 'abstract' nao tem endpoint proprio: vem do biblio, em outra arvore.
        docs = _lista(corpo.get("exchange-documents", {}).get("exchange-document"))
        partes = []
        for d in docs:
            if not isinstance(d, dict):
                continue
            abs_ = _lista(d.get("abstract"))
            # O mesmo documento traz o resumo em varias linguas; 'en' e a que da
            # para citar. Sem 'en', fica a primeira -- melhor texto em alemao do
            # que campo vazio lido como 'o documento nao revela nada'.
            en = next((a for a in abs_ if isinstance(a, dict) and a.get("@lang") == "en"), None)
            for a in ([en] if en else abs_):
                if isinstance(a, dict) and a.get("p") is not None:
                    partes.extend(_texto(p) for p in _lista(a["p"]))
                else:
                    partes.append(_texto(a))
        texto = "\n\n".join(p for p in partes if p)

    return {
        "referencia": referencia,
        "secao": secao,
        "disponivel": bool(texto),
        "texto": texto,
        # Escape hatch: quando o achatamento nao pegar tudo, o bruto continua la.
        "bruto_json": bruto if not texto else None,
    }


def _folhas(no: Any, caminho: tuple = ()):
    """Todo par (caminho, valor) da arvore. O OPS alterna dict e lista para o mesmo
    campo e prefixa com 'reg:' de forma irregular -- caminhar e mais barato que
    acertar o formato exato de cada variante."""
    if isinstance(no, dict):
        for k, v in no.items():
            yield from _folhas(v, caminho + (k,))
    elif isinstance(no, list):
        for x in no:
            yield from _folhas(x, caminho)
    else:
        yield caminho, no


def _ids_publicacao(no: Any):
    """Dicts que identificam uma publicacao (tem 'kind' e 'date').

    O Register prefixa as chaves com 'reg:' e o published-data nao. Comparar pelo
    sufixo cobre os dois sem um ramo por servico.
    """
    if isinstance(no, dict):
        por_sufixo = {str(x).split(":")[-1]: x for x in no}
        if "kind" in por_sufixo and "date" in por_sufixo:
            yield {"kind": no[por_sufixo["kind"]], "date": no[por_sufixo["date"]]}
        for v in no.values():
            yield from _ids_publicacao(v)
    elif isinstance(no, list):
        for x in no:
            yield from _ids_publicacao(x)


def _acha(no: Any, chave: str) -> Any:
    """Primeiro valor cuja chave termina em 'chave', em qualquer profundidade.

    Poupa cravar o caminho inteiro ('ops:register-search' / 'reg:register-documents'
    / 'reg:register-document' / ...), que muda entre servicos do OPS.
    """
    if isinstance(no, dict):
        for k, v in no.items():
            if str(k).split(":")[-1] == chave:
                return v
        for v in no.values():
            achado = _acha(v, chave)
            if achado is not None:
                return achado
    elif isinstance(no, list):
        for x in no:
            achado = _acha(x, chave)
            if achado is not None:
                return achado
    return None


_RE_PAIS = re.compile(r"^[A-Z]{2}$")


@mcp.tool()
def epo_register(referencia: str) -> dict:
    """Estados designados e mencao de concessao de um EP, pelo European Patent Register.

    USE QUANDO: precisar saber ONDE uma patente europeia pode ter sido validada.

    POR QUE ISTO IMPORTA: em BE, FR, GB, GR, IE, IT, LU, NL e SE o Acordo de Londres
    dispensa a traducao, entao a validacao NAO gera publicacao nacional -- nao existe
    membro de familia INPADOC e nenhuma busca por familia acha o caso. Num cliente
    real, 46 de 59 casos eram invisiveis assim.

    ⚠️ LEIA ANTES DE USAR 'estados_designados': desde 2009 o deposito designa TODOS os
    estados contratantes de uma vez, entao esta lista vem com ~39 paises em qualquer
    EP. Ela e o TETO do que poderia ter sido validado -- NAO e lista de candidatos, e
    muito menos de validacoes. Tratar os 39 como carteira inventa 39 casos por
    patente. O que a lista serve para dizer e uma coisa so: se o associado mencionar
    validacao num estado, ele estava designado.

    O QUE DE FATO SE APROVEITA AQUI e 'mencao_de_concessao': e a publicacao do B1 no
    Boletim Europeu, e dela corre o prazo de validacao nacional (art. 65 EPC, em regra
    3 meses). Esse prazo e calculavel SEM depender de publicacao nacional -- e por
    isso e o unico prazo dos paises de Londres que da para projetar.

    LIMITES: so cobre pedidos EP (e PCT designando o EPO) e so aceita formato epodoc.
    O Register nao publica em que estados houve validacao efetiva; nenhuma fonte
    publica isso. So a lista do escritorio sabe.
    """
    ref = re.sub(r"[\s.\-/]", "", (referencia or "").upper())
    if not ref.startswith("EP"):
        return {
            "erro": True,
            "mensagem": (
                f"'{referencia}' nao e um EP. O European Patent Register so cobre "
                "pedidos europeus e PCT que designam o EPO."
            ),
        }
    try:
        resp = cliente().register(
            reference_type="publication", input=epo_ops.models.Epodoc(ref)
        )
    except Exception as e:
        if _sem_resultado(e):
            return {"referencia": referencia, "encontrado": False, "estados_designados": [],
                    "mensagem": ("O Register nao tem este documento. Ausencia aqui NAO e "
                                 "prova de que nao houve designacao.")}
        raise

    _loga_quota("register", resp)
    corpo = resp.json().get("ops:world-patent-data", {})

    designados = sorted({
        v for caminho, v in _folhas(corpo)
        if any("designation-of-states" in str(k) for k in caminho)
        # o valor pode vir cru ou dentro de {'$': 'AT'} -- olha os dois ultimos passos
        and any(str(k).endswith("country") for k in caminho[-2:])
        and _RE_PAIS.match(str(v))
    })

    # A mencao de concessao e a publicacao do B1 no Boletim Europeu -- e dela que
    # corre o prazo de validacao nacional.
    concessoes = sorted({
        _texto(d.get("date")) for d in _ids_publicacao(corpo)
        if _texto(d.get("kind")).upper().startswith("B") and _texto(d.get("date"))
    })

    # Situacao mais recente do Register ('The patent has been granted', 'No opposition
    # filed within time limit', 'Grant of patent is intended', ...).
    estados_ep = sorted(
        (
            (str(d.get("@change-date") or ""), _texto(d.get("$")))
            for d in _lista(_acha(corpo, "ep-patent-status"))
            if isinstance(d, dict)
        ),
        reverse=True,
    )

    # Data de deposito do EP: e a data-base da anuidade em todo estado validado, e
    # sem ela a validacao entra na carteira sem prazo nenhum.
    app = _acha(corpo, "application-reference")
    deposito = next(
        (d["date"] for d in _ids_publicacao({"x": app}) if _texto(d.get("date"))), None
    )
    if not deposito:
        deposito = next((_texto(v) for cam, v in _folhas(app or {})
                         if str(cam[-1]).endswith("date") or
                         (len(cam) > 1 and str(cam[-2]).endswith("date"))), None)

    return {
        "referencia": referencia,
        "encontrado": True,
        "data_deposito": _texto(deposito) or None,
        "mencao_de_concessao": concessoes[0] if concessoes else None,
        "situacao": estados_ep[0][1] if estados_ep else None,
        "situacao_em": estados_ep[0][0] if estados_ep else None,
        "estados_designados": designados,
        "total_designados": len(designados),
        "aviso": (
            "DESIGNACAO NAO E VALIDACAO, E NAO E NEM CANDIDATURA. Desde 2009 o deposito "
            f"designa todos os estados contratantes de uma vez -- por isso vieram "
            f"{len(designados)}. A lista e o TETO do que poderia ter sido validado. "
            "Nenhuma fonte publica diz onde houve validacao efetiva: nos paises do "
            "Acordo de Londres (BE, FR, GB, GR, IE, IT, LU, NL, SE) a validacao nao "
            "gera publicacao nacional. So a lista do escritorio sabe. O dado acionavel "
            "aqui e 'mencao_de_concessao', de onde corre o prazo do art. 65 EPC."
        ),
        "bruto_json": None if designados else json.dumps(corpo, ensure_ascii=False),
    }


_RE_REF_PAIS = re.compile(r"Ref Country Code\s+([A-Z]{2})")

# Codigos INPADOC que o proprio escritorio nacional reporta ao EPO. Sao os unicos
# que dizem alguma coisa sobre o pais, e nao sobre o processo europeu.
CADUCOU = "PG25"      # LAPSED IN A CONTRACTING STATE
TAXA_PAGA = "PGFP"    # ANNUAL FEE PAID TO NATIONAL OFFICE
ATO_NACIONAL = "REG"  # REFERENCE TO A NATIONAL CODE


@mcp.tool()
def epo_status_legal(referencia: str, apenas_nacionais: bool = True) -> dict:
    """Status legal INPADOC de um documento, com os eventos separados POR PAIS.

    USE QUANDO: precisar saber onde a patente ainda esta viva, onde caducou, e onde
    houve ato nacional depois da concessao.

    POR QUE IMPORTA PARA A VALIDACAO EUROPEIA: nos paises do Acordo de Londres a
    validacao nao gera publicacao nacional, entao a familia INPADOC nao mostra nada.
    Mas o escritorio nacional REPORTA eventos ao EPO, e eles aparecem aqui. Num EP
    real vieram atos nacionais de IE, NL, SE, GR, DK, PT e ES -- paises que a busca
    por familia nao enxerga. Isto e evidencia, nao suposicao.

    COMO LER cada classificacao:
      caducou        PG25, o escritorio nacional comunicou a extincao. E afirmacao.
      taxa_paga      PGFP, anuidade paga ao escritorio nacional. E afirmacao.
      ato_nacional   REG, houve ato no pais -- mas o codigo nacional pode significar
                     tanto registro da traducao quanto extincao (em CH, 'PL' e
                     lapso). NAO leia como 'esta viva': leia como 'aconteceu algo la,
                     confira o codigo'.

    REGRA DE OURO, a mesma do resto do projeto: isto e registro do PASSADO. O INPADOC
    nao publica 'vence em novembro'. Ausencia de evento nao e prova de ausencia de
    direito -- e frequentemente so atraso do escritorio nacional.

    Args:
        apenas_nacionais: mantem so os eventos que carregam pais (PG25, PGFP, REG).
            Desligue para ver tambem a prosecucao europeia (exame, concessao, oposicao).
    """
    try:
        resp = cliente().legal(reference_type="publication", input=_entrada(referencia))
    except Exception as e:
        if _sem_resultado(e):
            return {"referencia": referencia, "encontrado": False, "eventos": [],
                    "mensagem": ("O INPADOC nao tem status legal deste documento. "
                                 "Ausencia NAO e prova de que nao ha direito vigente.")}
        raise

    _loga_quota("legal", resp)
    corpo = resp.json().get("ops:world-patent-data", {})

    eventos = []
    for e in _lista(_acha(corpo, "legal")):
        if not isinstance(e, dict):
            continue
        pre = "  ".join(
            _texto(p.get("$")) for p in _lista(e.get("ops:pre")) if isinstance(p, dict)
        )
        achado = _RE_REF_PAIS.search(pre)
        codigo = str(e.get("@code") or "").strip()
        if apenas_nacionais and not achado:
            continue
        eventos.append({
            "codigo": codigo,
            "descricao": str(e.get("@desc") or "").strip(),
            "pais": achado.group(1) if achado else None,
            "data": _texto(e.get("ops:L007EP")),
            "texto": pre,
        })

    por_pais: dict = {}
    for ev in eventos:
        if not ev["pais"]:
            continue
        p = por_pais.setdefault(ev["pais"], {"caducou": False, "taxa_paga": False,
                                             "atos": 0, "ultimo_evento": None})
        if ev["codigo"] == CADUCOU:
            p["caducou"] = True
        elif ev["codigo"] == TAXA_PAGA:
            p["taxa_paga"] = True
        elif ev["codigo"] == ATO_NACIONAL:
            p["atos"] += 1
        if ev["data"] and (not p["ultimo_evento"] or ev["data"] > p["ultimo_evento"]):
            p["ultimo_evento"] = ev["data"]

    return {
        "referencia": referencia,
        "encontrado": True,
        "total_eventos": len(eventos),
        "paises_com_evento_nacional": sorted(por_pais),
        "caducado_em": sorted(p for p, v in por_pais.items() if v["caducou"]),
        "taxa_nacional_paga_em": sorted(p for p, v in por_pais.items() if v["taxa_paga"]),
        "por_pais": dict(sorted(por_pais.items())),
        "eventos": eventos,
        "aviso": (
            "Registro do PASSADO, nunca calendario. O INPADOC nao publica vencimento "
            "futuro. Ausencia de evento num pais nao prova ausencia de direito: pode "
            "ser so atraso do escritorio nacional em reportar ao EPO. E 'ato_nacional' "
            "(REG) NAO significa 'esta viva' -- o codigo nacional pode ser de extincao."
        ),
    }


TETO_SEMANAL_BYTES = 4 * 1024**3  # free tier do EPO: 4 GB por semana


@mcp.tool()
def epo_quota(dias: int = 7) -> dict:
    """Quanto da cota do EPO ja foi gasto na janela. O teto e 4 GB por semana.

    USE QUANDO: for expandir familia de carteira grande, ou antes de uma varredura.

    POR QUE EXISTE: a API do EPO NAO expoe contador de consumo. Sem esta leitura, o
    teto so aparece quando ja foi estourado -- e a partir dai toda busca falha, o que
    num dia de prazo e o pior momento possivel. Cada chamada bem-sucedida grava os
    bytes em inpi/data/epo_quota.log; aqui so somamos.

    LIMITE: contamos os bytes da RESPOSTA. O EPO contabiliza do lado dele e pode
    divergir. Trate como ordem de grandeza, nao como extrato.
    """
    if not QUOTA_LOG.exists():
        return {"erro": True, "mensagem": f"Sem log de cota em {QUOTA_LOG}."}

    corte = datetime.now(timezone.utc).timestamp() - dias * 86400
    total, chamadas, por_op, ilegiveis = 0, 0, {}, 0
    for linha in QUOTA_LOG.read_text(encoding="utf-8").splitlines():
        partes = linha.split("\t")
        if len(partes) != 3:
            ilegiveis += 1
            continue
        ts, op, tam = partes
        try:
            # duas escritas convivem no mesmo arquivo: epo_mcp grava ISO 8601 e
            # familia_epo grava epoch. Ler so uma delas subestimaria o consumo.
            quando = (datetime.fromisoformat(ts).timestamp() if "-" in ts
                      else float(ts))
            n = int(tam)
        except ValueError:
            ilegiveis += 1
            continue
        if quando < corte:
            continue
        total += n
        chamadas += 1
        base = op.split(":")[0]
        por_op[base] = por_op.get(base, 0) + n

    pct = total / TETO_SEMANAL_BYTES
    return {
        "janela_dias": dias,
        "chamadas": chamadas,
        "bytes": total,
        "mb": round(total / 1024**2, 2),
        "teto_semanal_gb": 4,
        "percentual_do_teto": round(pct * 100, 4),
        "bytes_por_operacao": dict(sorted(por_op.items(), key=lambda x: -x[1])),
        "linhas_ilegiveis": ilegiveis,
        "alerta": (
            "ACIMA DE 80% DA COTA SEMANAL. Pare de expandir familia e reduza a faixa "
            "das buscas -- estourar o teto derruba TODA consulta ao EPO ate a virada "
            "da semana." if pct > 0.8 else ""
        ),
    }


from epo.topico import epo_panorama_topico  # noqa: E402,F401  (registra na mcp acima)


if __name__ == "__main__":
    mcp.run()
