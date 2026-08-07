"""Saude de portfolio: um score 0-100 por titular, para abrir reuniao -- Fase 3,
reescrito na Fase G para rodar do TITULAR REAL (base INPI), sem depender de
upload manual de carteira.

E HEURISTICA DE TRIAGEM, nao avaliacao juridica: mistura sinais de portfolio
(vigencia, idade, diversidade tecnologica) computados so da base INPI local --
score de titular sem processo BR e erro, nao zero. "lacunas" vem sempre junto,
nunca so o numero.

O SCORE NAO CHAMA REDE: os quatro componentes saem de _carregar_lote (base INPI
local), rapidos e deterministicos. O bloco 'exterior' (validacao de vigencia no
exterior via EPO, incluindo o Acordo de Londres) e SEPARADO, opcional e limitado
por max_casos_exterior -- nunca entra no score nem trava a resposta, e so roda
automatico para cliente CURADO (Clarke Modet). Assim o numero e sempre estavel
e a checagem cara de exterior fica isolada.

Componentes (100 pts):
  vigencia                40  fracao de casos ainda ativos (nao encerrados)
  qualidade_dos_dados     30  fracao com data de deposito conhecida (base de projecao)
  diversidade_tecnologica 15  subclasses IPC distintas, capada em 8 (substitui a antiga
                             'cobertura_geografica', que exigia carteira ingerida)
  idade_do_portfolio      15  decai linearmente ate 20 anos a partir da idade media
"""

from __future__ import annotations

from datetime import date

from inpi.mcp_app import mcp
from inpi.prazos import _carregar_lote

TETO_SUBCLASSES_PARA_PONTUACAO = 8
ANOS_PARA_ZERAR_IDADE = 20
PAISES_LONDRES = {"BE", "FR", "GB", "GR", "IE", "IT", "LU", "NL", "SE"}


def _subclasses_ipc(numeros: list[str]) -> int:
    """Subclasses IPC distintas (4 chars) num conjunto de processos BR."""
    if not numeros:
        return 0
    from inpi.consulta import _linhas

    linhas = _linhas(
        "SELECT DISTINCT substr(simbolo, 1, 4) sc FROM ipc "
        "WHERE numero_inpi IN (SELECT unnest(?::VARCHAR[])) "
        "AND simbolo IS NOT NULL AND length(simbolo) >= 4",
        [numeros],
    )
    return len(linhas)


def _score(estados: dict, hoje: date) -> dict:
    total = len(estados)
    ativos = [e for e in estados.values() if not e["encerrado_em"]]
    com_data = [e for e in estados.values() if e.get("data_deposito")]

    p_vig = round(40 * len(ativos) / total, 1)
    p_qual = round(30 * len(com_data) / total, 1)

    n_sub = _subclasses_ipc(list(estados.keys()))
    p_div = round(15 * min(n_sub, TETO_SUBCLASSES_PARA_PONTUACAO)
                  / TETO_SUBCLASSES_PARA_PONTUACAO, 1)

    idades = [(hoje - e["data_deposito"]).days / 365
              for e in estados.values() if e.get("data_deposito")]
    idade_media = round(sum(idades) / len(idades), 1) if idades else None
    p_idade = (round(15 * max(0.0, 1 - (idade_media or 0) / ANOS_PARA_ZERAR_IDADE), 1)
               if idade_media is not None else 0.0)

    lacunas = []
    faltando = total - len(com_data)
    if faltando:
        lacunas.append(f"{faltando} caso(s) sem data de deposito (nao entra em projecao)")
    if n_sub <= 1:
        lacunas.append("portfolio concentrado numa unica subclasse tecnologica")
    if len(ativos) < total:
        lacunas.append(f"{total - len(ativos)} caso(s) ja encerrado(s) (indeferido/arquivado/extinto)")

    return {
        "score": round(p_vig + p_qual + p_div + p_idade, 1),
        "componentes": {
            "vigencia": {"pontos": p_vig, "de": 40,
                         "casos_ativos": len(ativos), "casos_totais": total},
            "qualidade_dos_dados": {"pontos": p_qual, "de": 30,
                                    "casos_com_data_deposito": len(com_data)},
            "diversidade_tecnologica": {"pontos": p_div, "de": 15,
                                        "subclasses_ipc_distintas": n_sub},
            "idade_do_portfolio": {"pontos": p_idade, "de": 15,
                                   "idade_media_anos": idade_media},
        },
        "lacunas": lacunas,
    }


def _exterior(cliente: str, max_casos: int) -> dict:
    """Bloco exterior: reusa carteira_auditoria_vigencia (Fase E/F), que ja faz
    a checagem via EPO Register/status legal -- inclusive Acordo de Londres. NAO
    entra no score. So chamado quando pedido/curado. Bounded por max_casos."""
    from inpi.vigencia import carteira_auditoria_vigencia

    aud = carteira_auditoria_vigencia(cliente, max_casos=max_casos)
    caducados_londres = sorted({
        a["pais"] for a in aud.get("alertas_caducidade", [])
        if a.get("pais") in PAISES_LONDRES
    })
    return {
        "casos_auditados": aud.get("casos_auditados"),
        "alertas_caducidade": aud.get("alertas_caducidade", []),
        "caducidade_em_paises_de_londres": caducados_londres,
        "qualidade_cadastro": aud.get("qualidade_dados", []),
        "nota": aud.get("aviso"),
    }


@mcp.tool()
def carteira_saude(cliente: str, hoje: str | None = None,
                   incluir_exterior: bool | None = None,
                   max_casos_exterior: int = 15) -> dict:
    """Score 0-100 de saude do portfolio de um titular, com os componentes
    explicitos e as lacunas que explicam o numero.

    USE QUANDO: precisar de UM numero para abrir reuniao de cliente, sem perder
    de vista o que sustenta esse numero.

    O score sai so da base INPI local (rapido, sem rede). O bloco 'exterior'
    (vigencia no exterior via EPO, inclui Acordo de Londres) e separado e NAO
    entra no score. Roda automatico so para cliente curado (Clarke Modet);
    passe incluir_exterior=True para forcar em qualquer titular.

    Args:
        cliente: nome do titular.
        hoje: 'AAAA-MM-DD' de referencia; default a data corrente.
        incluir_exterior: None = automatico (so curado); True/False forca.
        max_casos_exterior: teto de casos consultados no EPO (quota 4GB/semana).
    """
    from inpi.titulares import chave_de, resolver

    d_hoje = date.fromisoformat(hoje) if hoje else date.today()
    chave = chave_de(cliente)
    norm = resolver(chave)

    estados, _ = _carregar_lote(titular=cliente)
    if not estados:
        return {
            "erro": True,
            "cliente": cliente,
            "normalizacao": norm,
            "mensagem": (f"Nenhum processo BR para {cliente!r} na base INPI. Score "
                         "de titular sem processo e erro, nao zero -- confira a grafia."),
        }

    corpo = _score(estados, d_hoje)

    rodar_ext = norm["nivel"] == "curada" if incluir_exterior is None else incluir_exterior
    exterior = _exterior(cliente, max_casos_exterior) if rodar_ext else {
        "nota": ("nao consultado -- exterior so roda automatico para cliente curado; "
                 "passe incluir_exterior=True para forcar.")
    }

    return {
        "cliente": cliente,
        "referencia": d_hoje.isoformat(),
        "normalizacao": norm,
        "score": corpo["score"],
        "componentes": corpo["componentes"],
        "lacunas": corpo["lacunas"],
        "exterior": exterior,
        "aviso": (
            "HEURISTICA DE TRIAGEM, nao avaliacao juridica. O score sai so da base "
            "BR local; 'exterior' e checagem EPO separada e limitada, nao entra no "
            "numero. Leia 'lacunas' antes de citar o score para o cliente."
        ),
    }
