"""Limitador de taxa + retry + cache compartilhado pelas fontes de
enriquecimento (Google Patents, EPO texto integral já tem o seu próprio em
epo/epo_mcp.py, Espacenet).

Por que existe: a postura é agressiva em COBERTURA (raspar onde não há API
oficial), não em VOLUME -- um IP banido zera a cobertura pra todo mundo. Um
único limitador compartilhado evita reimplementar isso em cada fonte e garante
que o intervalo mínimo por host vale mesmo se harness.py chamar fontes
diferentes em sequência rápida.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import requests
from dogpile.cache import make_region
from dogpile.cache.api import NO_VALUE

RAIZ = Path(__file__).resolve().parent
CACHE_DBM = RAIZ / "data" / "cache.dbm"
TTL_CACHE = 60 * 60 * 24 * 7  # 1 semana: página de patente publicada não muda de um dia p/ outro

# Espacenet fica atrás de Cloudflare (challenge-platform observado na Fase 0
# de descoberta) -- o mais cauteloso dos três, de propósito.
INTERVALO_MIN_SEGUNDOS = {
    "patents.google.com": 2.0,
    "patentscope.wipo.int": 3.0,
    "worldwide.espacenet.com": 5.0,
    "busca.inpi.gov.br": 2.0,
}
INTERVALO_PADRAO = 3.0

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_ultima_requisicao: dict[str, float] = {}
_sessao = requests.Session()
_sessao.headers.update({"User-Agent": USER_AGENT})


@dataclass
class RespostaHTTP:
    """Subconjunto de requests.Response que cabe no cache (picklable, sem
    referência de conexão de rede)."""
    status_code: int
    text: str
    url: str


def _regiao_cache():
    """Mesmo padrão de epo/epo_mcp.py: dbm persistente onde `fcntl` existe
    (Linux/Render), memória (só dentro do processo) no Windows."""
    try:
        import fcntl  # noqa: F401
    except ImportError:
        return make_region().configure("dogpile.cache.memory", expiration_time=TTL_CACHE)
    CACHE_DBM.parent.mkdir(parents=True, exist_ok=True)
    return make_region().configure(
        "dogpile.cache.dbm", expiration_time=TTL_CACHE,
        arguments={"filename": str(CACHE_DBM)},
    )


_cache = _regiao_cache()


def _espera(host: str) -> None:
    intervalo = INTERVALO_MIN_SEGUNDOS.get(host, INTERVALO_PADRAO)
    ultima = _ultima_requisicao.get(host)
    if ultima is not None:
        falta = intervalo - (time.monotonic() - ultima)
        if falta > 0:
            time.sleep(falta)
    _ultima_requisicao[host] = time.monotonic()


def requisitar(metodo: str, url: str, host: str, tentativas: int = 3,
               timeout: float = 15.0, usar_cache: bool = True,
               **kwargs) -> RespostaHTTP | None:
    """GET/POST com rate-limit por host, cache de 1 semana (só GET com status
    200) e retry com backoff exponencial em erro de rede/429/5xx. Devolve None
    (nunca levanta) se todas as tentativas falharem -- quem chama decide como
    declarar a falha ao usuário, no mesmo espírito de inpi/pdf_inpi.py."""
    chave_cache = f"{metodo}:{url}" if usar_cache and metodo == "get" else None
    if chave_cache:
        resultado_em_cache = _cache.get(chave_cache)
        if resultado_em_cache is not NO_VALUE:
            return resultado_em_cache

    for tentativa in range(tentativas):
        _espera(host)
        try:
            resp = _sessao.request(metodo, url, timeout=timeout, **kwargs)
        except requests.RequestException:
            time.sleep(2 ** tentativa)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(2 ** tentativa)
            continue
        # requests so confia no charset do header Content-Type; sem ele, cai no
        # default ISO-8859-1 da RFC 2616 e produz mojibake ('Ã' no lugar de 'Ç')
        # em paginas UTF-8 sem charset declarado -- caso do Google Patents.
        if resp.encoding is None or resp.encoding.lower() in ("iso-8859-1", "latin-1"):
            resp.encoding = resp.apparent_encoding or "utf-8"
        resultado = RespostaHTTP(status_code=resp.status_code, text=resp.text, url=resp.url)
        if chave_cache and resultado.status_code == 200:
            _cache.set(chave_cache, resultado)
        return resultado
    return None
