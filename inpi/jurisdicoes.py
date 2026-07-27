"""Regras de anuidade/manutencao por jurisdicao, e prazo de entrada em fase nacional.

REGRA DE OURO DESTE MODULO: so projeta quem foi revisado por profissional habilitado.

Brasil tem evidencia empirica nesta base -- a regra do art. 84 foi calibrada contra
285.409 despachos de anuidade e bate com mediana de -0,04 ano. Nenhuma outra
jurisdicao tem evidencia alguma aqui: sao regras transcritas de legislacao, sujeitas
a erro de transcricao e a desatualizacao, e nao ha nada nos dados que as confirme.

Por isso o comportamento e assimetrico de proposito:
  - jurisdicao calibrada/revisada  -> devolve datas projetadas
  - jurisdicao NAO-REVISADA        -> devolve a REGRA e a base legal, sem datas,
                                      e instrui a confirmar com o associado local

Isso e a mesma disciplina aplicada aos codigos de despacho do INPI: a tabela e dado
revisado por humano, nao codigo. Para liberar uma jurisdicao, preencha 'revisado_por'
e 'revisado_em' em referencias/anuidades-por-jurisdicao.csv.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from anuidades import _mais_meses

TABELA = Path(__file__).resolve().parent / "referencias" / "anuidades-por-jurisdicao.csv"

# Uma jurisdicao so projeta datas se estiver aqui.
CONFIANCA_QUE_PROJETA = {"calibrado-empiricamente", "revisado"}


@dataclass
class Regra:
    jurisdicao: str
    nome: str
    tipo_taxa: str          # 'anuidade' ou 'manutencao'
    data_base: str          # 'deposito' ou 'concessao'
    primeira: int | None
    periodicidade: str      # 'anual', 'quinquenal', 'marcos'
    marcos: list[float]     # anos da data_base, quando periodicidade='marcos'
    dias_apos_concessao: int | None  # 1o pagamento devido N dias apos a concessao
    graca_meses: int
    vigencia_anos: int
    fase_nacional_meses: int | None
    base_legal: str
    fonte: str
    revisado_por: str
    confianca: str

    revisado_em: str = ""

    @property
    def projeta(self) -> bool:
        # Exige revisado_por E revisado_em, como o docstring do modulo promete.
        # A versao anterior aceitava so um dos dois e furava a trava.
        revisado = bool(self.revisado_por) and bool(self.revisado_em)
        return self.confianca in CONFIANCA_QUE_PROJETA or revisado


def _int(v, padrao=None):
    v = (v or "").strip()
    return int(float(v)) if v else padrao


def carregar() -> dict[str, Regra]:
    regras = {}
    with TABELA.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            j = r["jurisdicao"].strip().upper()
            regras[j] = Regra(
                jurisdicao=j,
                nome=r["nome"],
                tipo_taxa=r["tipo_taxa"],
                data_base=r["data_base"],
                primeira=_int(r["primeira"]),
                periodicidade=r["periodicidade"],
                marcos=[float(x) for x in r["marcos"].split(";") if x.strip()],
                dias_apos_concessao=_int(r.get("dias_apos_concessao")),
                graca_meses=_int(r["prazo_graca_meses"], 0),
                vigencia_anos=_int(r["vigencia_anos"], 20),
                fase_nacional_meses=_int(r["prazo_fase_nacional_meses"]),
                base_legal=r["base_legal"],
                fonte=r["fonte"],
                revisado_por=r["revisado_por"].strip(),
                confianca=r["confianca"].strip(),
                revisado_em=r.get("revisado_em", "").strip(),
            )
    return regras


def descrever(jurisdicao: str) -> dict:
    """A regra de uma jurisdicao, em linguagem util -- projete ou nao."""
    r = carregar().get((jurisdicao or "").strip().upper())
    if not r:
        return {"erro": True, "mensagem": f"Jurisdicao '{jurisdicao}' nao esta na tabela."}

    if r.periodicidade == "marcos":
        quando = (
            f"taxas de manutencao em {', '.join(str(m) for m in r.marcos)} anos "
            f"contados da {r.data_base}"
        )
    else:
        quando = (
            f"{r.periodicidade}, a partir da {r.primeira}a, contada da {r.data_base}"
        )

    return {
        "jurisdicao": r.jurisdicao,
        "nome": r.nome,
        "tipo": r.tipo_taxa,
        "quando": quando,
        "prazo_de_graca_meses": r.graca_meses,
        "vigencia_anos": r.vigencia_anos,
        "prazo_entrada_fase_nacional_meses": r.fase_nacional_meses,
        "base_legal": r.base_legal,
        "confianca": r.confianca,
        "projeta_datas": r.projeta,
        "aviso": (
            f"Regra {r.confianca}. {r.fonte}"
            if r.projeta
            else "REGRA NAO REVISADA. Transcrita de legislacao, sem verificacao contra "
                 "dado e sem revisao de profissional habilitado -- nao ha nada nesta "
                 "base que a confirme. Serve para orientar a conversa com o associado "
                 "local, NUNCA para controlar prazo. Para liberar a projecao de datas, "
                 "preencha 'revisado_por' e 'revisado_em' em "
                 "referencias/anuidades-por-jurisdicao.csv."
        ),
    }


def fase_nacional(data_prioridade: date, jurisdicoes: list[str] | None = None) -> dict:
    """Prazo de entrada em fase nacional do PCT, contado da prioridade mais antiga.

    Este e o unico prazo internacional que projetamos mesmo sem revisao, porque o
    marco (30 ou 31 meses da prioridade) e uniforme e vem do proprio PCT, nao da lei
    interna de cada pais. Ainda assim, confirme com o associado: ha jurisdicoes com
    restauracao e com prazo estendido mediante taxa.
    """
    regras = carregar()
    alvos = [j.strip().upper() for j in (jurisdicoes or regras.keys())]
    saida, desconhecidas, sem_prazo = [], [], []
    for j in alvos:
        r = regras.get(j)
        if not r:
            desconhecidas.append(j)
            continue
        if not r.fase_nacional_meses:
            sem_prazo.append(j)
            continue
        saida.append({
            "jurisdicao": j,
            "nome": r.nome,
            "meses": r.fase_nacional_meses,
            "prazo": _mais_meses(data_prioridade, r.fase_nacional_meses).isoformat(),
        })
    saida.sort(key=lambda x: x["prazo"])

    r = {
        "data_prioridade": data_prioridade.isoformat(),
        "prazos": saida,
        "aviso": (
            "Contado da prioridade mais antiga, conforme o PCT (art. 22 e 39). Alguns "
            "escritorios admitem restauracao ou extensao mediante taxa. Confirme com o "
            "associado local antes de agir -- perder este prazo e irreversivel na maioria "
            "das jurisdicoes."
        ),
    }
    # Omitir jurisdicao pedida e nao respondida seria o pior tipo de silencio: o
    # operador acharia que nao ha prazo la, num prazo que nao se recupera.
    if desconhecidas:
        r["nao_encontradas"] = desconhecidas
        r["alerta_nao_encontradas"] = (
            f"NAO estao na tabela e por isso NAO foram calculadas: "
            f"{', '.join(desconhecidas)}. Ausencia aqui nao significa ausencia de prazo "
            "-- acrescente em referencias/anuidades-por-jurisdicao.csv ou pergunte ao "
            "associado."
        )
    if sem_prazo:
        r["sem_prazo_de_fase_nacional"] = sem_prazo
    return r
