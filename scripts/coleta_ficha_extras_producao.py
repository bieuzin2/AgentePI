"""Producao (nao piloto): dispara a coleta cheia de uma das duas frentes
validadas no piloto (ver scripts/coleta_ficha_extras_piloto.py).

Roda uma vez sobre a populacao inteira -- sem rodadas/convergencia, o
candidato e fixo (nao expande como o bootstrap antigo expandia). Dedupe
automatico via registrar()/CSV: pode ser interrompido e reiniciado sem
retrabalho, so reprocessa quem ainda nao esta no CSV curado.

Rode:
    python scripts/coleta_ficha_extras_producao.py frente1  [paralelismo]
    python scripts/coleta_ficha_extras_producao.py frente2  [paralelismo]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import inpi.db as dbmod  # noqa: E402

# Com Tor + isolamento por credencial SOCKS, cada worker sai por um exit node
# proprio (ver inpi/tor_proxy.py). Paralelismo alto entao nao empilha carga num
# circuito unico -- cada no ve so 1 worker (~0,7 req/s). O gargalo antigo (todos
# os workers num circuito Tor compartilhado) sumiu.
#
# asyncio (aiohttp+aiohttp-socks) foi testado nesta sessao como alternativa a
# threading e DESCARTADO: medido mais lento mesmo sem concorrencia (fetch
# isolado ~15s async vs ~9s threading, mesmo daemon) -- overhead do proprio
# stack aiohttp_socks/python-socks pra este proxy, nao algo que compense com
# mais paralelismo. Threading + mais daemons Tor continua o caminho que rende.
PARALELISMO_PADRAO = 10


def _candidatos_frente1() -> list[str]:
    linhas = dbmod.con().execute("""
        SELECT DISTINCT p.numero_inpi FROM procuradores p
        JOIN escritorios e ON e.original = p.procurador
        WHERE e.chave = 'CLARKE MODET'
    """).fetchall()
    return [r[0] for r in linhas]


def _candidatos_frente2() -> list[str]:
    linhas = dbmod.con().execute("""
        SELECT b.numero_inpi FROM biblio b
        LEFT JOIN procuradores p USING (numero_inpi)
        WHERE b.sigilo = 1 AND p.numero_inpi IS NULL
    """).fetchall()
    return [r[0] for r in linhas]


# Top concorrentes da Clarke por volume de pedidos (chave normalizada de
# inpi.escritorios). Ampliar ficha-extras a eles: os dados (CPC/anuidades/
# peticoes) sao POR PEDIDO, independem do escritorio -- o vinculo
# escritorio->pedido ja vive no banco (procuradores JOIN escritorios), entao
# "extras dos pedidos do escritorio X" e um JOIN em query-time, sem duplicar
# nada aqui. O rotulo escritorio_canonico gravado e so proveniencia do lote.
# A consolidacao fina de grafias (ex.: 'NELLIE ANNE DANIEL SHORES' vs
# 'NELLIE D SHORES', que a chave ainda nao une) fica pra depois, no banco,
# sem re-raspar.
CONCORRENTES = [
    "DANNEMANN SIEMSEN BIGLER IPANEMA MOREIRA",
    "MOMSEN LEONARDOS",
    "KASZNAR LEONARDOS",
    "DANIEL ALT DE DANIEL",
    "DAVID DO NASCIMENTO",
    "MONTAURY PIMENTA MACHADO VIEIRA DE MELLO",
    "ANTONIO MAURICIO PEDRAS ARNAUD",
    "LUIZ LEONARDOS",
    "LICKS",
    "BHERING",
]


def _candidatos_escritorio(chave: str) -> list[str]:
    linhas = dbmod.con().execute("""
        SELECT DISTINCT p.numero_inpi FROM procuradores p
        JOIN escritorios e ON e.original = p.procurador
        WHERE e.chave = ?
    """, [chave]).fetchall()
    return [r[0] for r in linhas]


def rodar_concorrentes(paralelismo: int) -> None:
    """Raspa ficha-extras dos pedidos dos top concorrentes, um escritorio por
    LOTE (resumivel: cada lote pula os ja coletados via _coletados()). Roda em
    ordem, do maior pro menor -- se interromper, o proximo run retoma de onde
    parou sem reprocessar lote inteiro ja concluido."""
    from inpi.coleta_ficha_extras import varrer_e_registrar_paralelo

    t_geral = time.time()
    for i, chave in enumerate(CONCORRENTES, 1):
        candidatos = _candidatos_escritorio(chave)
        print(f"[{i}/{len(CONCORRENTES)}] {chave}: {len(candidatos):,} pedidos, "
              f"paralelismo={paralelismo}", flush=True)
        t0 = time.time()
        resumo = varrer_e_registrar_paralelo(candidatos, chave, paralelismo=paralelismo)
        print(f"  concluido em {(time.time()-t0)/3600:.1f}h: {resumo}", flush=True)
    print(f"Concorrentes concluidos em {(time.time()-t_geral)/3600:.1f}h", flush=True)


def rodar_frente1(paralelismo: int) -> None:
    from inpi.coleta_ficha_extras import varrer_e_registrar_paralelo

    candidatos = _candidatos_frente1()
    print(f"Frente 1: {len(candidatos):,} candidatos, paralelismo={paralelismo}", flush=True)
    t0 = time.time()
    resumo = varrer_e_registrar_paralelo(candidatos, "CLARKE MODET", paralelismo=paralelismo)
    print(f"Frente 1 concluida em {(time.time()-t0)/3600:.1f}h: {resumo}", flush=True)


def rodar_frente2(paralelismo: int) -> None:
    from inpi.coleta_sigilo import varrer_e_registrar_geral_paralelo

    candidatos = _candidatos_frente2()
    print(f"Frente 2: {len(candidatos):,} candidatos, paralelismo={paralelismo}", flush=True)
    t0 = time.time()
    resumo = varrer_e_registrar_geral_paralelo(candidatos, paralelismo=paralelismo)
    print(f"Frente 2 concluida em {(time.time()-t0)/3600:.1f}h: {resumo}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("frente1", "frente2", "concorrentes"):
        print("uso: python scripts/coleta_ficha_extras_producao.py frente1|frente2|concorrentes [paralelismo]")
        sys.exit(1)
    paralelismo = int(sys.argv[2]) if len(sys.argv) > 2 else PARALELISMO_PADRAO
    if sys.argv[1] == "frente1":
        rodar_frente1(paralelismo)
    elif sys.argv[1] == "concorrentes":
        rodar_concorrentes(paralelismo)
    else:
        rodar_frente2(paralelismo)
