"""Saude de portfolio: um score 0-100 por carteira de cliente, para abrir
reuniao -- plano-v2 Fase 3.

E HEURISTICA DE TRIAGEM, nao avaliacao juridica: mistura sinais de qualidade de
dado (o quanto sabemos sobre a carteira) com sinais de portfolio (vigencia,
diversidade geografica, idade). Score baixo pode significar carteira fraca OU
carteira mal cadastrada -- por isso "lacunas" vem sempre junto, nunca so o
numero.

Nao chama rede (EPO/BigQuery): usa so o que ja esta na tabela `casos` de
carteira.duckdb (carteira.listar), que precisa ter sido povoada antes por
carteira_ingerir/carteira_descobrir/landscape_carteira. Score de carteira vazia
e erro, nao zero -- zero sugeriria "carteira ruim" quando na verdade e
"carteira nao cadastrada".

Componentes (100 pts):
  vigencia            40  fracao de casos ainda ativos (nao caducado/encerrado)
  qualidade_dos_dados 30  fracao de casos com data-base e sem conflito entre fontes
  cobertura_geografica 15  diversidade de jurisdicoes, capada em 8 (teto arbitrario,
                          documentado -- nao ha "numero certo" de paises)
  idade_do_portfolio  15  decai linearmente ate 20 anos (vigencia maxima de invencao
                          no Brasil) a partir da idade media de deposito
"""

from __future__ import annotations

from datetime import date

from inpi import carteira as ct
from inpi.mcp_app import mcp

TETO_JURISDICOES_PARA_PONTUACAO = 8
ANOS_PARA_ZERAR_IDADE = 20


def _pontos_vigencia(casos: list[dict]) -> tuple[float, int, int]:
    ativos = [c for c in casos if (c.get("status") or "").strip().lower()
              not in ("caducado", "encerrado")]
    return round(40 * len(ativos) / len(casos), 1), len(ativos), len(casos)


def _pontos_qualidade(casos: list[dict], conflitos: list[dict]) -> tuple[float, list[str]]:
    com_data_base = [c for c in casos if c.get("data_base")]
    numeros_em_conflito = {c["numero_norm"] for c in conflitos}
    sem_conflito = [c for c in casos if c["numero_norm"] not in numeros_em_conflito]
    fracao = (len(com_data_base) / len(casos) + len(sem_conflito) / len(casos)) / 2
    problemas = []
    faltando = len(casos) - len(com_data_base)
    if faltando:
        problemas.append(f"{faltando} caso(s) sem data-base (nao entra em projecao de prazo)")
    if conflitos:
        problemas.append(f"{len(conflitos)} conflito(s) de data entre fontes")
    return round(30 * fracao, 1), problemas


def _pontos_cobertura(casos: list[dict]) -> tuple[float, int]:
    n = len({c["jurisdicao"] for c in casos})
    return round(15 * min(n, TETO_JURISDICOES_PARA_PONTUACAO) / TETO_JURISDICOES_PARA_PONTUACAO, 1), n


def _pontos_idade(casos: list[dict], hoje: date) -> tuple[float, float | None]:
    idades = [
        (hoje - c["data_deposito"]).days / 365
        for c in casos if c.get("data_deposito")
    ]
    if not idades:
        return 0.0, None
    media = sum(idades) / len(idades)
    pontos = round(15 * max(0.0, 1 - media / ANOS_PARA_ZERAR_IDADE), 1)
    return pontos, round(media, 1)


@mcp.tool()
def carteira_saude(cliente: str, hoje: str | None = None) -> dict:
    """Score 0-100 de saude da carteira de um cliente, com os componentes
    explicitos e a lista de lacunas que explicam o numero.

    USE QUANDO: precisar de UM numero para abrir reuniao de cliente, sem
    perder de vista o que sustenta esse numero.

    Requer carteira ja povoada (carteira_ingerir, carteira_descobrir ou
    landscape_carteira) -- nao consulta rede.

    Args:
        cliente: nome do cliente na carteira (ver carteira_ingerir/carteira_listar).
        hoje: 'AAAA-MM-DD' de referencia para idade/vigencia; default a data corrente.
    """
    d_hoje = date.fromisoformat(hoje) if hoje else date.today()
    try:
        cart = ct.listar(cliente)
    except RuntimeError as e:
        return {"erro": True, "mensagem": str(e)}
    casos = cart["casos"]
    if not casos:
        return {
            "erro": True,
            "mensagem": (
                f"Nenhum caso na carteira de {cliente!r}. Score de carteira vazia "
                "e erro, nao zero -- rode carteira_ingerir ou carteira_descobrir "
                "antes."
            ),
        }

    p_vigencia, ativos, total = _pontos_vigencia(casos)
    p_qualidade, problemas_qualidade = _pontos_qualidade(casos, cart["conflitos"])
    p_cobertura, n_jurisdicoes = _pontos_cobertura(casos)
    p_idade, idade_media = _pontos_idade(casos, d_hoje)
    score = round(p_vigencia + p_qualidade + p_cobertura + p_idade, 1)

    lacunas = list(problemas_qualidade)
    if n_jurisdicoes <= 1:
        lacunas.append("carteira concentrada numa unica jurisdicao")
    if cart["sem_data_base"]:
        lacunas.append(f"{len(cart['sem_data_base'])} caso(s) sem data-base nenhuma")

    from inpi.titulares import PROVENIENCIA_CARTEIRA

    return {
        "cliente": cliente, "referencia": d_hoje.isoformat(),
        "proveniencia": PROVENIENCIA_CARTEIRA,
        "score": score,
        "componentes": {
            "vigencia": {"pontos": p_vigencia, "de": 40,
                        "casos_ativos": ativos, "casos_totais": total},
            "qualidade_dos_dados": {"pontos": p_qualidade, "de": 30},
            "cobertura_geografica": {"pontos": p_cobertura, "de": 15,
                                     "jurisdicoes_distintas": n_jurisdicoes},
            "idade_do_portfolio": {"pontos": p_idade, "de": 15,
                                   "idade_media_anos": idade_media},
        },
        "lacunas": lacunas,
        "aviso": (
            "HEURISTICA DE TRIAGEM, nao avaliacao juridica de portfolio. Mistura "
            "qualidade do cadastro com sinais de carteira -- score baixo por "
            "'qualidade_dos_dados' significa carteira mal cadastrada, nao "
            "carteira fraca. Leia 'lacunas' antes de citar o numero para o cliente."
        ),
    }
