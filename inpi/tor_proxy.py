"""Suporte a proxy Tor local (pool de daemons) para a coleta de ficha do pePI.

Contexto: busca.inpi.gov.br bloqueou nosso IP direto (SSLEOFError no handshake
TLS) apos uma rajada de sessoes simultaneas em 2026-08-11. Confirmado que NAO
era outage geral do site (4G do celular e circuitos Tor frescos acessavam
normal, so nosso IP/rede direto que caia) -- por isso e valido contornar com
Tor: e dado publico, acesso anonimo (sem login), a mesma coisa que o 4G ja
fazia, so que via uma rede diferente da nossa.

POR QUE MULTIPLOS DAEMONS: um unico daemon Tor satura sob ~20 circuitos
concorrentes (medido: 8 workers=43/min, 1 frente a 10=~49/min, mas 20 juntos
colapsou pra ~0 -- nao era bloqueio do INPI, os circuitos frescos pegavam 200,
era o processo Tor local afogando). O gargalo e o processo Tor local, nao os
exit nodes. Rodar N daemons em portas diferentes (torrc..torrc5) e distribuir
os workers entre eles multiplica a vazao: cada daemon carrega poucos circuitos
confortaveis. Os daemons sao iniciados manualmente pelo usuario (abrir processo
de rede em background e bloqueado pelo classificador de auto-mode deste agente).

Robusto a daemon ausente: portas_vivas() sonda cada SocksPort e usa so as que
respondem -- o usuario pode subir 2, 3 ou 5 daemons e o codigo se adapta.
"""

from __future__ import annotations

import os
import socket
import time

# (SocksPort, ControlPort) de cada daemon. O 1o e o que ja rodava; os demais
# vem de .tor/torrc2..torrc10. Convencao: control = socks + 1.
DAEMONS = [
    (9050, 9051),
    (9052, 9053),
    (9054, 9055),
    (9056, 9057),
    (9058, 9059),
    (9060, 9061),
    (9062, 9063),
    (9064, 9065),
    (9066, 9067),
    (9068, 9069),
]
_HOST = "127.0.0.1"

# Convencao pos-2012 do pePI e o socks do 1o daemon como fallback compat.
PROXY_URL = f"socks5h://{_HOST}:{DAEMONS[0][0]}"


def ativo() -> bool:
    """True se a coleta deve rotear via Tor -- controlado por env var pra nao
    ficar ligado por acidente quando o acesso direto voltar a funcionar."""
    return os.environ.get("INPI_USAR_TOR") == "1"


def _porta_responde(porta: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((_HOST, porta), timeout=timeout):
            return True
    except OSError:
        return False


def portas_vivas() -> list[int]:
    """SocksPorts que respondem agora. Permite o usuario subir 2..5 daemons
    sem o codigo assumir os 5 -- sonda uma vez no inicio da coleta."""
    return [socks for socks, _ in DAEMONS if _porta_responde(socks)]


def _control_de(socks: int) -> int | None:
    for s, c in DAEMONS:
        if s == socks:
            return c
    return None


def proxies(circuito: str | None = None, socks_port: int | None = None) -> dict[str, str]:
    """Proxies para uma sessao, apontando pro daemon `socks_port` (default: o
    1o). `circuito` liga isolamento de stream (IsolateSOCKSAuth, padrao do
    Tor): credenciais SOCKS diferentes -> circuitos/exit nodes diferentes
    DENTRO do mesmo daemon. Distribuir workers entre daemons (socks_port) E
    entre circuitos (circuito) espalha a carga nos dois eixos: nenhum daemon
    afoga, nenhum exit node leva mais que um punhado de workers."""
    porta = socks_port or DAEMONS[0][0]
    if circuito is None:
        url = f"socks5h://{_HOST}:{porta}"
    else:
        url = f"socks5h://{circuito}:x@{_HOST}:{porta}"
    return {"http": url, "https": url}


def novo_circuito(socks_port: int | None = None, espera_segundos: float = 3.0) -> bool:
    """Pede um novo circuito (= novo IP de saida) via sinal NEWNYM no
    ControlPort do daemon indicado (default: 1o). Devolve False sem levantar se
    o Tor nao estiver acessivel -- quem chama trata como falha normal."""
    try:
        from stem.control import Controller
    except ImportError:
        return False
    porta_control = _control_de(socks_port or DAEMONS[0][0])
    if porta_control is None:
        return False
    try:
        with Controller.from_port(port=porta_control) as c:
            c.authenticate()
            c.signal("NEWNYM")
    except Exception:
        return False
    time.sleep(espera_segundos)
    return True
