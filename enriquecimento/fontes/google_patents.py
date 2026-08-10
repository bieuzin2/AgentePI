"""Google Patents (patents.google.com): fonte PRIMÁRIA de reivindicações e
citações -- inclusive para pedidos BR depositados diretamente, sem passagem
PCT/WO, que é o buraco que nem o EPO OPS nem o PATENTSCOPE cobrem (ambos só
têm texto integral de EP/WO).

Verificado ao vivo na Fase 0 de descoberta (2026-08-10, via claude-in-chrome):
'patents.google.com/patent/{doc_id}/{idioma}' é HTML server-side renderizado
(app Polymer antigo), sem sessão, sem XHR, sem captcha -- um GET simples com
cache/rate-limit (ver enriquecimento/limitador.py) basta. Estrutura confirmada:
heading <h2>/<h3> com texto começando em 'Claims' seguido de um elemento
<patent-text> com o texto integral das reivindicações; heading 'Patent
Citations'/'Cited By' seguido de uma <table> com uma célula por documento
citado na primeira coluna.

LIMITE: o doc_id do Google Patents inclui o kind code (ex. 'U2', 'A2', 'B1'),
que o INPI não expõe direto pelo número de processo. `_candidatos_doc_id`
tenta os kind codes mais comuns nesta ordem; a primeira resposta 200 com a
seção esperada reconhecida vence. Quando o doc_id já é conhecido (ex.: membro
de família resolvido por outra fonte), passe-o direto e pule a tentativa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from enriquecimento.limitador import requisitar

BASE = "https://patents.google.com/patent"
HOST = "patents.google.com"

# Ordem por frequência observada na base BR: pedido de patente (A2, A8, A9),
# modelo de utilidade (U2), carta patente concedida (B1, C1).
KIND_CODES_BR = ["A2", "U2", "B1", "A8", "C1", "A9"]

_RE_ITEM_REIVINDICACAO = re.compile(r"^\s*(\d{1,3})\s*[.\-–)]\s*\)?\s*", re.M)


def _candidatos_doc_id(numero_normalizado: str) -> list[str]:
    return [f"BR{numero_normalizado}{k}" for k in KIND_CODES_BR]


def quadro_reivindicatorio(texto: str) -> list[dict]:
    """Mesma heurística de numeração de inpi/pdf_inpi.py (linha começando em
    'N.'), para o claim chart tratar as duas fontes de forma idêntica."""
    if not texto.strip():
        return []
    marcas = list(_RE_ITEM_REIVINDICACAO.finditer(texto))
    if not marcas:
        return [{"numero": None, "texto": texto.strip()}]
    itens = []
    for i, m in enumerate(marcas):
        inicio = m.end()
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        itens.append({"numero": int(m.group(1)), "texto": texto[inicio:fim].strip()})
    return itens


def extrair_claims(html: str) -> list[dict] | None:
    """Reivindicações a partir de <section itemprop="claims">. None se a seção
    não existir -- nunca inventa texto a partir de outra seção da página.

    Estrutura confirmada no HTML BRUTO (não no DOM pós-hidratação do Polymer,
    que usa uma tag <patent-text> só client-side e não existe na resposta
    HTTP crua -- essa era a suposição inicial, corrigida após teste ao vivo):
    <section itemprop="claims"><h2>Claims (<span itemprop="count">N</span>)</h2>
    <div itemprop="content">...<div class="claim-text">1 .) texto</div>...</section>
    """
    soup = BeautifulSoup(html, "html.parser")
    secao = soup.find("section", attrs={"itemprop": "claims"})
    if secao is None:
        return None
    bloco = secao.find(attrs={"itemprop": "content"}) or secao
    texto = bloco.get_text("\n", strip=True)
    return quadro_reivindicatorio(texto) if texto else None


# 'backwardReferences*' = documentos que ESTE documento cita (estado da
# tecnica apontado no exame); 'forwardReferences*' = documentos que citam
# ESTE documento. Cada um aparece em ate duas variantes de itemprop
# ('Orig'/'Family', conforme fonte do dado no INPADOC) para o MESMO par
# documento-citado -- dedup por (tipo, doc) evita contar a mesma citacao 2x.
_PREFIXO_TIPO = {"backwardReferences": "citando", "forwardReferences": "citada_por"}


def extrair_citacoes(html: str) -> list[dict]:
    """Citações a partir das linhas <tr itemprop="backwardReferences*"|
    "forwardReferences*"> + <span itemprop="publicationNumber"> dentro delas.
    Lista vazia é uma resposta válida (comum em modelos de utilidade, que
    raramente têm citação registrada) -- não é o mesmo que falha de rede/parse."""
    soup = BeautifulSoup(html, "html.parser")
    achados: list[dict] = []
    vistos: set[tuple[str, str]] = set()
    for linha in soup.find_all("tr", attrs={"itemprop": True}):
        prop = linha["itemprop"]
        base = prop.replace("Orig", "").replace("Family", "")
        tipo = _PREFIXO_TIPO.get(base)
        if tipo is None:
            continue
        span = linha.find("span", attrs={"itemprop": "publicationNumber"})
        if span is None:
            continue
        doc = span.get_text(strip=True)
        chave = (tipo, doc)
        if doc and chave not in vistos:
            vistos.add(chave)
            achados.append({"tipo": tipo, "doc_citado": doc})
    return achados


@dataclass
class ResultadoClaims:
    ok: bool
    doc_id: str | None
    reivindicacoes: list[dict] = field(default_factory=list)
    fonte: str = "google_patents"
    mensagem: str = ""


@dataclass
class ResultadoCitacoes:
    ok: bool
    doc_id: str | None
    citacoes: list[dict] = field(default_factory=list)
    fonte: str = "google_patents"
    mensagem: str = ""


def _buscar_pagina(cid: str, idioma: str):
    url = f"{BASE}/{cid}/{idioma}"
    return requisitar("get", url, host=HOST)


def buscar_claims(numero_normalizado: str, doc_id: str | None = None,
                   idioma: str = "pt") -> ResultadoClaims:
    """Busca reivindicações no Google Patents.

    Com `doc_id` informado (ex.: membro de família já resolvido por outra
    fonte), usa direto -- caminho mais confiável. Sem `doc_id`, tenta os kind
    codes mais comuns para BR até achar um doc_id válido com seção de Claims.
    """
    candidatos = [doc_id] if doc_id else _candidatos_doc_id(numero_normalizado)
    ultima_msg = "nenhum candidato tentado"
    for cid in candidatos:
        resp = _buscar_pagina(cid, idioma)
        if resp is None:
            ultima_msg = f"{cid}: sem resposta do Google Patents após retries"
            continue
        if resp.status_code != 200:
            ultima_msg = f"{cid}: HTTP {resp.status_code}"
            continue
        claims = extrair_claims(resp.text)
        if claims:
            return ResultadoClaims(ok=True, doc_id=cid, reivindicacoes=claims)
        ultima_msg = f"{cid}: página encontrada mas sem seção de Claims reconhecida"
    return ResultadoClaims(ok=False, doc_id=None, mensagem=ultima_msg)


def buscar_citacoes(numero_normalizado: str, doc_id: str | None = None,
                     idioma: str = "en") -> ResultadoCitacoes:
    """Busca citando/citadas no Google Patents. Reusa o cache de
    `buscar_claims` para o mesmo doc_id -- chamar as duas para o mesmo número
    custa uma única requisição de rede quando o idioma bate."""
    candidatos = [doc_id] if doc_id else _candidatos_doc_id(numero_normalizado)
    ultima_msg = "nenhum candidato tentado"
    for cid in candidatos:
        resp = _buscar_pagina(cid, idioma)
        if resp is None:
            ultima_msg = f"{cid}: sem resposta do Google Patents após retries"
            continue
        if resp.status_code != 200:
            ultima_msg = f"{cid}: HTTP {resp.status_code}"
            continue
        citacoes = extrair_citacoes(resp.text)
        return ResultadoCitacoes(
            ok=True, doc_id=cid, citacoes=citacoes,
            mensagem="" if citacoes else "documento sem seção de citações (comum em modelos de utilidade)",
        )
    return ResultadoCitacoes(ok=False, doc_id=None, mensagem=ultima_msg)
