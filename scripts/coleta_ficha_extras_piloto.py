"""Piloto (amostra pequena, nao fatia sequencial) das duas frentes de coleta
de ficha antes do run de producao:

- Frente 1 (inpi.coleta_ficha_extras): CPC/peticoes/anuidades pra uma amostra
  da carteira Clarke, misturando formato moderno/antigo e pedido velho/novo.
- Frente 2 (inpi.coleta_sigilo.varrer_e_registrar_geral_paralelo): procurador
  de uma amostra de sigilosos de QUALQUER escritorio (nao so Clarke).

Objetivo: catalogar cobertura real (% com CPC, % com anuidade, % com peticao),
confirmar que formato antigo e moderno funcionam, e reportar um resumo antes
de disparar a raspagem cheia (45 mil pedidos Frente 1, 43 mil Frente 2). Nao
grava nada que a producao nao gravaria -- roda contra os CSVs curados de
verdade (procuradores-sigilo.csv, ficha-extras.csv), so em volume pequeno.

Rode: python scripts/coleta_ficha_extras_piloto.py [tamanho_amostra]
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import inpi.db as dbmod  # noqa: E402
from inpi.coleta_ficha_extras import _le_csv as le_ficha_extras  # noqa: E402
from inpi.coleta_ficha_extras import varrer_e_registrar_paralelo as coletar_ficha_extras  # noqa: E402
from inpi.coleta_sigilo import _RE_NUMERO_MODERNO  # noqa: E402
from inpi.coleta_sigilo import varrer_e_registrar_geral_paralelo  # noqa: E402

TAMANHO_PADRAO = 120


def _amostra_clarke(n: int) -> list[str]:
    """Metade formato moderno, metade antigo (se existir o bastante) -- e
    justamente o que a producao vai enfrentar em proporcao real (~43% da
    carteira Clarke e formato antigo, ver plano)."""
    linhas = dbmod.con().execute("""
        SELECT DISTINCT p.numero_inpi
        FROM procuradores p JOIN escritorios e ON e.original = p.procurador
        WHERE e.chave = 'CLARKE MODET'
    """).fetchall()
    numeros = [r[0] for r in linhas]
    modernos = [x for x in numeros if _RE_NUMERO_MODERNO.match(x)]
    antigos = [x for x in numeros if not _RE_NUMERO_MODERNO.match(x)]
    metade = n // 2
    random.shuffle(modernos)
    random.shuffle(antigos)
    return modernos[:metade] + antigos[:n - metade]


def _amostra_sigilosos(n: int) -> list[str]:
    linhas = dbmod.con().execute("""
        SELECT b.numero_inpi FROM biblio b
        LEFT JOIN procuradores p USING (numero_inpi)
        WHERE b.sigilo = 1 AND p.numero_inpi IS NULL
    """).fetchall()
    numeros = [r[0] for r in linhas]
    random.shuffle(numeros)
    return numeros[:n]


_RE_ENABLE_HIDE = re.compile(r"EnableHide\('([^']+)'\)")


def investigar_link_documento(html: str) -> str | None:
    """Best-effort: o link de 'Documentos Publicados' nao e um <a href> --
    ver docstring de inpi/coleta_ficha_extras.py. So confirma se o marcador
    EnableHide('PatentDocument') existe na ficha; NAO tenta adivinhar o
    endpoint por proximidade de <img src=...> -- tentativa anterior pegou
    falso positivo (bt_layer.gif, o icone generico de fechar painel que
    aparece em varias secoes, nao o documento). Resolver isso de verdade
    exige inspecionar a chamada JS/rede de perto, fora do escopo deste
    piloto -- fica registrado como trabalho futuro."""
    return "EnableHide('PatentDocument') presente" if _RE_ENABLE_HIDE.search(html) else None


def rodar(tamanho_amostra: int = TAMANHO_PADRAO) -> None:
    print(f"=== Piloto: {tamanho_amostra} pedidos por frente ===\n", flush=True)

    print("--- Frente 1: ficha-extras (carteira Clarke) ---", flush=True)
    amostra_clarke = _amostra_clarke(tamanho_amostra)
    n_moderno = sum(1 for x in amostra_clarke if _RE_NUMERO_MODERNO.match(x))
    print(f"amostra: {len(amostra_clarke)} ({n_moderno} formato moderno, "
          f"{len(amostra_clarke) - n_moderno} formato antigo)", flush=True)
    resumo_extras = coletar_ficha_extras(amostra_clarke, "CLARKE MODET", paralelismo=4)
    print("resumo:", resumo_extras, flush=True)

    linhas_novas = [r for r in le_ficha_extras() if r["numero_inpi"] in set(amostra_clarke)]
    total = len(linhas_novas) or 1
    com_cpc = sum(1 for r in linhas_novas if r["cpc"])
    com_anuidade = sum(1 for r in linhas_novas if r["anuidades_json"] not in ("", "[]"))
    com_peticao = sum(1 for r in linhas_novas if r["peticoes_json"] not in ("", "[]"))
    print(f"cobertura (sobre {total} coletados): "
          f"CPC {com_cpc}/{total} ({com_cpc/total:.0%}), "
          f"anuidade {com_anuidade}/{total} ({com_anuidade/total:.0%}), "
          f"peticao {com_peticao}/{total} ({com_peticao/total:.0%})", flush=True)

    print("\n--- Frente 2: procurador universal de sigilosos ---", flush=True)
    amostra_sigilosos = _amostra_sigilosos(tamanho_amostra)
    print(f"amostra: {len(amostra_sigilosos)} sigilosos (qualquer escritorio)", flush=True)
    resumo_sigilo = varrer_e_registrar_geral_paralelo(amostra_sigilosos, paralelismo=4)
    print("resumo:", resumo_sigilo, flush=True)

    print("\n--- Link de documento (best-effort) ---", flush=True)
    achados = 0
    for numero in amostra_clarke[:10]:
        from inpi.coleta_sigilo import _Trabalhador
        t = _Trabalhador()
        if not t.sessao_anonima():
            continue
        html = t.ficha_html(numero)
        if html is None:
            continue
        achado = investigar_link_documento(html)
        if achado:
            achados += 1
            print(f"  {numero}: {achado}", flush=True)
    if achados == 0:
        print("  nenhum indicio de endpoint direto nas 10 fichas checadas -- "
              "fica como trabalho futuro, nao resolvido no piloto.", flush=True)

    print("\n=== Fim do piloto -- revisar cobertura acima antes de disparar producao ===")


if __name__ == "__main__":
    tamanho = int(sys.argv[1]) if len(sys.argv) > 1 else TAMANHO_PADRAO
    rodar(tamanho)
