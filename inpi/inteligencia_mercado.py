"""Inteligencia de mercado: quem e o responsavel de PI de uma empresa-alvo.

Objetivo de negocio (ponto 3 do refinamento): "estar no lugar certo, na hora
certa" para negociar com clientes potenciais NAO-Clarke. Responde "quem cuida de
PI/patentes na empresa X e em que eventos (ABPI/AIPPI/INTA/congresso INPI) essa
pessoa costuma aparecer".

FRONTEIRA DE FONTE -- por que este modulo existe separado e devolve fonte explicita:
o alvo primario de consumo e o M365 Copilot, que TAMBEM pode ter acesso a internet.
A regra de ouro e nunca fundir dado curado com dado da web. Esta tool devolve APENAS
o que foi curado a mao (referencias/responsaveis-pi.csv), sempre marcado
fonte="curadoria interna". Quando nao ha registro, devolve encontrado=false com
instrucao explicita de que SO ENTAO o agente pode recorrer a busca na internet, e
que o resultado web deve ser rotulado como tal. Ver remoto/CLAUDE.md.

LGPD: o CSV guarda nome de PESSOA FISICA. Uso e prospeccao comercial B2B a partir de
dado profissional publico; ainda assim a saida carrega o mesmo aviso de dado pessoal
que inpi/mercado.py aplica. So cure dados de fonte publica profissional.
"""

from __future__ import annotations

import csv
import unicodedata
from functools import lru_cache
from pathlib import Path

from inpi.mcp_app import mcp
from inpi.titulares import chave_de, resolver

CSV = Path(__file__).resolve().parent / "referencias" / "responsaveis-pi.csv"

_AVISO_PESSOAL = (
    "Contem PESSOA FISICA (nome/cargo profissional). Uso de prospeccao B2B a partir "
    "de dado publico profissional; confira base legal (LGPD art. 7o) antes de tratar."
)


def _norm(s: str) -> str:
    """Chave de casamento: sem acento, maiuscula, espacos colapsados. Mesma
    disciplina de normalizacao do resto do projeto, para 'Nubank' casar com
    'NU BANK' e afins na medida do possivel."""
    t = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return " ".join(t.split())


@lru_cache(maxsize=1)
def _curados() -> list[dict]:
    """Le o CSV curado uma vez por processo. Ignora a linha-exemplo semente."""
    if not CSV.exists():
        return []
    with CSV.open(encoding="utf-8", newline="") as fh:
        linhas = list(csv.DictReader(fh))
    return [
        r for r in linhas
        if _norm(r.get("empresa_canonica", "")) not in ("", "EXEMPLO SUBSTITUA")
    ]


@mcp.tool()
def inpi_responsavel_pi(empresa: str) -> dict:
    """Quem cuida de PI/patentes numa empresa-alvo, e em que eventos costuma aparecer.

    USE QUANDO: o operador quiser prospectar e perguntar 'quem e o responsavel de
    PI da empresa X' ou 'quem da empresa X vai a eventos de patentes'. So devolve
    dado CURADO a mao (fonte='curadoria interna'), nunca da internet.

    Se encontrado=false, ESTA tool nao tem o dado: so entao o agente pode buscar na
    web, e deve rotular o resultado como vindo da internet, jamais fundir com dado
    curado ou com dado do INPI. NAO invente o responsavel.

    Args:
        empresa: nome da empresa-alvo (titular). Casa por nome normalizado.
    """
    alvo = _norm(empresa)
    curados = _curados()
    achados = [
        r for r in curados
        if alvo and (alvo in _norm(r["empresa_canonica"])
                     or _norm(r["empresa_canonica"]) in alvo)
    ]

    # Resolve a empresa contra a base de titulares do INPI -- ajuda o agente a
    # confirmar que a empresa existe/deposita no Brasil, mesmo quando nao ha
    # responsavel curado. E dado do INPI, mantido em bloco separado do curado.
    # Best-effort: se a base de titulares nao estiver carregada, o curado ainda vale.
    try:
        chave = chave_de(empresa)
        titular_inpi = resolver(chave) if chave else {"nivel": "nao_encontrado"}
    except Exception:
        titular_inpi = {"nivel": "indisponivel",
                        "nota": "base de titulares do INPI nao carregada neste ambiente"}

    if not achados:
        return {
            "empresa_consultada": empresa,
            "encontrado": False,
            "titular_no_inpi": titular_inpi,
            "instrucao_agente": (
                "Nao ha responsavel de PI curado para esta empresa. SO AGORA o agente "
                "pode buscar na internet (LinkedIn publico, programas de eventos ABPI/"
                "AIPPI/INTA/INPI). Rotule o resultado como 'fonte: internet', nunca o "
                "apresente como dado do MCP nem o funda com o dado do INPI acima. "
                "Ofereca curar o achado no responsaveis-pi.csv."
            ),
        }

    return {
        "empresa_consultada": empresa,
        "encontrado": True,
        "fonte": "curadoria interna",
        "responsaveis": achados,
        "titular_no_inpi": titular_inpi,
        "aviso_dado_pessoal": _AVISO_PESSOAL,
        "nota": (
            "Dado curado a mao. Nao misture com informacao da internet. Se o agente "
            "complementar com a web, apresente as duas fontes separadas e rotuladas."
        ),
    }
