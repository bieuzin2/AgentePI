"""Freedom-To-Operate (liberdade de operacao) sob a territorialidade da LPI 9.279/96.

Porta a ideia do app legado (que cruzava EPO) para dentro deste repo, SEM Lens:
classifica cada documento/familia numa de tres situacoes de FTO, aplicando o
principio de que patente e um direito TERRITORIAL -- a protecao se limita ao pais
que concedeu (LPI art. 42 c/c art. 40; a Convencao de Paris consagra a
independencia das patentes, art. 4bis). Logo, para explorar ALGO NO BRASIL o que
importa e se ha membro de familia VIVO no INPI/BR; um equivalente vivo nos EUA nao
impede a exploracao em territorio brasileiro.

  DOMINIO_PUBLICO_GLOBAL  nenhum membro da familia esta vivo em lugar nenhum
                          (expirado por tempo/caduco em toda parte) -> qualquer um
                          explora, em qualquer pais.
  LIVRE_NO_BRASIL         nao ha membro vivo no INPI/BR (nunca entrou, ou entrou e
                          morreu), mesmo que vivo no exterior -> livre para explorar
                          EM territorio brasileiro; o direito estrangeiro nao alcanca
                          o Brasil.
  REQUER_LICENCA          ha pelo menos um membro vivo no INPI/BR -> explorar no BR
                          pode infringir; exige licenca/analise de infracao.

DISCIPLINA (a mesma do resto do repo -- ver prazos.py, jurisdicoes.py):
- Isto e ORIENTATIVO, best-effort, NAO e parecer juridico definitivo nem opiniao de
  FTO. Nao substitui analise de infracao reivindicacao-a-reivindicacao por
  profissional habilitado.
- NUNCA afirma veredito sem evidencia. Na duvida, classifica REQUER_LICENCA (o lado
  conservador: melhor pedir licenca a mais do que infringir) e explica o porque.
- Cada item carrega base legal, a evidencia (quem esta vivo e onde) e a confianca.

FONTE DE VIVACIDADE:
- BR: base local do INPI (autoritativa) -- estado processual de prazos.py e vigencia
  do art. 40 de anuidades.py. Nao depende de rede.
- Exterior: familia INPADOC do EPO (familia_epo.familia) + status legal por pais
  (epo_status_legal). Bate a cota do EPO (4 GB/semana), por isso `incluir_exterior`
  e opcional -- sem ela nao se afirma DOMINIO_PUBLICO_GLOBAL (falta o "em lugar
  nenhum"), so se distingue REQUER_LICENCA de LIVRE_NO_BRASIL, que ja e afirmavel so
  com a base BR.
"""

from __future__ import annotations

import re
from datetime import date

from inpi import anuidades as anu
from inpi.consulta import normaliza_numero
from inpi.familia_epo import familia
from inpi.prazos import _carregar_lote
from inpi.titulares import chave_de, resolver

GLOBAL = "DOMINIO_PUBLICO_GLOBAL"
LIVRE_BR = "LIVRE_NO_BRASIL"
LICENCA = "REQUER_LICENCA"

# Prazo maximo de patente de invencao em quase toda jurisdicao (TRIPS art. 33: minimo
# de 20 anos do deposito). Usado SO para inferir morte-por-tempo de membro estrangeiro
# a partir da data de deposito dele -- e conservador: alguns paises tem menos, nenhum
# padrao tem mais, entao se 20 anos ja passaram o membro esta morto com folga.
TERMO_MAX_ANOS = 20

BASE_LEGAL = (
    "LPI 9.279/96: patente e direito territorial (art. 42 -- protecao limitada ao "
    "territorio nacional; Conv. Paris art. 4bis, independencia das patentes). "
    "Vigencia BR: art. 40, 20 anos do deposito (invencao) ou 15 (modelo de utilidade); "
    "o par. unico -- prazo minimo da concessao -- foi declarado inconstitucional (STF, "
    "ADI 5529, 2021) e nao e aplicado."
)


def _tipo_entrada(entrada: str) -> str:
    """referencia (numero de documento) ou titular (nome de cliente).

    Um numero de patente e majoritariamente digitos (opcional sigla de pais/kind);
    um titular e majoritariamente texto. So conta digitos vs letras -- suficiente para
    separar 'BR 10 2012 010731 2' / 'PI0803071' / 'EP1234567' de 'Petrobras'.
    """
    t = re.sub(r"[\s.\-/]", "", entrada or "")
    digitos = sum(c.isdigit() for c in t)
    letras = sum(c.isalpha() for c in t)
    return "referencia" if digitos >= 6 and digitos >= letras else "titular"


def _parse_data_epo(bruto: str | None) -> date | None:
    """Data do EPO ('YYYYMMDD') -> date. None quando ausente/invalida."""
    d = re.sub(r"\D", "", bruto or "")[:8]
    try:
        return date(int(d[:4]), int(d[4:6]), int(d[6:8])) if len(d) == 8 else None
    except ValueError:
        return None


def _status_br(est: dict | None, num: str, hoje: date) -> dict:
    """Vivacidade do membro BR a partir do estado ja carregado (nao consulta o banco).

    'vivo' e True/False/None. None = existe processo mas nao da para afirmar (sem data
    de deposito) -> tratado como conservador (REQUER_LICENCA) mais adiante.
    """
    if est is None or not est.get("despachos"):
        # Sem processo na base: nunca entrou no BR (ou esta fora da cobertura). Nao ha
        # direito brasileiro a respeitar -- mas registre a ressalva de cobertura.
        return {"vivo": False, "confianca": "media",
                "motivo": "nenhum processo correspondente no INPI (nunca entrou no BR "
                          "ou fora da cobertura da base local)"}
    if est.get("encerrado_em"):
        t = est.get("despacho_terminal") or {}
        return {"vivo": False, "confianca": "alta",
                "motivo": f"encerrado no INPI em {est['encerrado_em']} "
                          f"(despacho terminal {t.get('codigo_despacho')})"}
    dep = est.get("data_deposito")
    if not dep:
        return {"vivo": None, "confianca": "baixa",
                "motivo": "processo consta no INPI mas sem data de deposito -- vigencia "
                          "do art. 40 indeterminavel"}
    fim = anu.fim_vigencia(dep, num)
    if fim < hoje:
        return {"vivo": False, "confianca": "alta", "fim_vigencia": fim.isoformat(),
                "motivo": f"vigencia expirada em {fim.isoformat()} (art. 40 LPI, "
                          f"{anu.VIGENCIA_ANOS[anu.natureza(num)]} anos do deposito "
                          f"{dep.isoformat()})"}
    return {"vivo": True, "confianca": "alta", "fim_vigencia": fim.isoformat(),
            "motivo": f"ativo no INPI, sem despacho terminal e dentro da vigencia "
                      f"(fim em {fim.isoformat()}, art. 40 LPI)"}


def _status_exterior(num: str, hoje: date) -> dict:
    """Vivacidade dos membros ESTRANGEIROS da familia INPADOC. Bate a rede/cota EPO.

    Um membro estrangeiro conta como MORTO quando: ja passou o termo maximo de 20 anos
    do proprio deposito (TRIPS art. 33 -- morte por tempo, evidencia forte), OU o
    INPADOC registra caducidade (PG25) no pais. Caso contrario conta como POSSIVELMENTE
    VIVO (lado conservador). WO (publicacao PCT) nao e direito nacional e e ignorado.
    """
    fam = familia(num)
    if fam.get("erro") or not fam.get("membros"):
        return {"consultado": True, "conclusivo": False,
                "motivo": f"familia INPADOC indisponivel ({fam.get('erro') or 'sem membros'})",
                "vivos": [], "mortos": []}

    from epo.epo_mcp import epo_status_legal

    estrangeiros = [m for m in fam["membros"]
                    if m.get("pais") not in ("BR", "WO", None, "")]
    # Um unico epo_status_legal no membro EP cobre a familia inteira por pais (os
    # escritorios nacionais reportam caducidade ao EPO no membro EP) -- economiza cota.
    ep = next((m for m in fam["membros"] if m.get("pais") == "EP"), None)
    caduco: set[str] = set()
    if ep:
        try:
            caduco = set(epo_status_legal(ep["referencia"]).get("caducado_em", []))
        except Exception:
            caduco = set()  # sem status legal so perdemos evidencia de morte -> conservador

    vivos, mortos = [], []
    for m in estrangeiros:
        pais, ref = m.get("pais"), m.get("referencia")
        dep = _parse_data_epo(m.get("data_deposito"))
        expirado = dep is not None and anu._mais_anos(dep, TERMO_MAX_ANOS) < hoje
        if expirado:
            mortos.append({"pais": pais, "referencia": ref,
                           "motivo": f"termo de {TERMO_MAX_ANOS} anos do deposito "
                                     f"({dep.isoformat()}) expirado"})
        elif pais in caduco:
            mortos.append({"pais": pais, "referencia": ref,
                           "motivo": "caducidade registrada no INPADOC (PG25)"})
        else:
            vivos.append({"pais": pais, "referencia": ref,
                          "motivo": "sem evidencia de expiracao/caducidade -- "
                                    "possivelmente vivo (conservador)"})
    return {"consultado": True, "conclusivo": True,
            "membros_estrangeiros": len(estrangeiros), "vivos": vivos, "mortos": mortos}


def _links(num: str) -> dict:
    return {
        "espacenet": f"https://worldwide.espacenet.com/patent/search?q=BR{num}",
        "inpi": ("https://busca.inpi.gov.br/pePI/jsp/patentes/PatenteSearchBasico.jsp "
                 f"(busque por {num} -- o pePI e stateful e nao tem link direto)"),
    }


def _classificar(num: str, est: dict | None, hoje: date, incluir_exterior: bool) -> dict:
    br = _status_br(est, num, hoje)

    if br["vivo"] is True or br["vivo"] is None:
        # Membro BR vivo (ou vivacidade indeterminada, tratada conservadoramente):
        # explorar no BR pode infringir.
        situacao = LICENCA
        confianca = br["confianca"] if br["vivo"] is True else "baixa"
        evidencia = {"br": br}
        ext = None
    else:
        # BR morto/inexistente. Sem membro BR vivo, ja e LIVRE_NO_BRASIL. So o exterior
        # decide se promove a DOMINIO_PUBLICO_GLOBAL.
        ext = _status_exterior(num, hoje) if incluir_exterior else None
        evidencia = {"br": br}
        if ext is not None:
            evidencia["exterior"] = ext
        if ext and ext["conclusivo"] and not ext["vivos"]:
            situacao = GLOBAL
            # media: heuristica de tempo + INPADOC (registro do passado, incompleto).
            confianca = "media"
        else:
            situacao = LIVRE_BR
            confianca = br["confianca"]

    return {
        "referencia": num,
        "situacao_fto": situacao,
        "evidencia": evidencia,
        "base_legal": BASE_LEGAL,
        "confianca": confianca,
        "links": _links(num),
    }


def fto_dominio_publico(
    referencia_ou_titular: str,
    incluir_exterior: bool = True,
    hoje: str | None = None,
    max_casos: int = 20,
) -> dict:
    """Classifica documento(s) em situacao de Freedom-To-Operate sob a LPI 9.279/96.

    USE QUANDO: perguntarem "isto ja caiu em dominio publico?", "posso fabricar/vender
    X no Brasil sem infringir?", "a carteira do concorrente ainda protege no BR?".

    DOIS MODOS (detectados pelo formato da entrada):
      - REFERENCIA de documento ('BR 10 2012 010731 2', 'PI0803071', 'EP1234567'):
        classifica aquela familia.
      - TITULAR (nome de cliente/concorrente): classifica a carteira BR dele.

    Args:
        referencia_ou_titular: numero de documento OU nome de titular.
        incluir_exterior: consulta a familia INPADOC no EPO para verificar vivacidade
            fora do BR (custa cota EPO). Sem ela, o veredito DOMINIO_PUBLICO_GLOBAL
            fica indisponivel -- so se distingue LIVRE_NO_BRASIL de REQUER_LICENCA.
        hoje: 'AAAA-MM-DD' de referencia (reproducibilidade); default = data do sistema.
        max_casos: teto de casos classificados por chamada no modo titular (cota EPO).

    E ORIENTATIVO, nao parecer juridico. Ver o aviso na saida.
    """
    ref = date.fromisoformat(hoje) if hoje else date.today()
    tipo = _tipo_entrada(referencia_ou_titular)
    avisos = [
        "ORIENTATIVO, nao e parecer juridico nem opiniao de FTO: nao substitui analise "
        "de infracao reivindicacao-a-reivindicacao por profissional habilitado.",
    ]

    if tipo == "referencia":
        num = normaliza_numero(referencia_ou_titular)
        estados, _ = _carregar_lote(numeros=[num])
        pares = [(num, estados.get(num))]
        normalizacao = None
    else:
        estados, total = _carregar_lote(titular=referencia_ou_titular)
        nums = sorted(estados)
        pares = [(n, estados[n]) for n in nums[: max(1, min(max_casos, 100))]]
        normalizacao = resolver(chave_de(referencia_ou_titular))
        if len(nums) > len(pares):
            avisos.append(
                f"Carteira com {total} casos; classificados os primeiros {len(pares)} "
                f"(max_casos={max_casos}). Aumente max_casos para cobrir o resto -- "
                "atento a cota EPO se incluir_exterior=True."
            )

    if not incluir_exterior:
        avisos.append(
            "incluir_exterior=False: sem consultar a familia no exterior nao ha como "
            "afirmar DOMINIO_PUBLICO_GLOBAL (faltaria confirmar 'morto em lugar "
            "nenhum'). LIVRE_NO_BRASIL e REQUER_LICENCA seguem validos -- dependem so "
            "da base BR."
        )

    itens = [_classificar(n, e, ref, incluir_exterior) for n, e in pares]
    resumo = {
        "dominio_publico_global": sum(i["situacao_fto"] == GLOBAL for i in itens),
        "livre_no_brasil": sum(i["situacao_fto"] == LIVRE_BR for i in itens),
        "requer_licenca": sum(i["situacao_fto"] == LICENCA for i in itens),
    }
    avisos.append(
        "INPADOC/status legal e registro do PASSADO: ausencia de evento nao prova "
        "vivacidade nem extincao. 'possivelmente vivo' e o lado conservador, nao uma "
        "afirmacao de que ha direito vigente."
    )

    saida = {
        "entrada": referencia_ou_titular,
        "tipo_entrada": tipo,
        "hoje": ref.isoformat(),
        "itens": itens,
        "resumo": resumo,
        "avisos": avisos,
    }
    if normalizacao is not None:
        saida["normalizacao"] = normalizacao
    return saida
