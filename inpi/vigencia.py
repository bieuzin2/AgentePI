"""Auditoria de vigencia cruzada INPI x INPADOC (plano de refinamento, Fases E1+F2).

Cruza a projecao local de anuidades com o status legal REAL reportado ao EPO:
pega "membro estrangeiro caducou sem ninguem ver" e "projecao conta anuidade
de caso morto". Na mesma varredura (para nao gastar quota EPO duas vezes),
compara o titular INPI vs o titular da familia no EPO -- divergencia e flag
de qualidade de cadastro.

LIMITES DECLARADOS (nao escondidos):
- Status legal por pais so e confiavel para membros EP (validacoes nacionais
  reportam PG25/PGFP/REG ao EPO). Membros nao-EP entram como 'nao_auditados'.
- Quota EPO: 4 GB/semana. `max_casos` limita a varredura; rode por cliente
  sob demanda, nunca em loop por toda a base.
- INPADOC e registro do PASSADO: ausencia de evento nao prova vigencia.
"""

from __future__ import annotations

from inpi.escritorios import normalizar
from inpi.familia_epo import familia
from inpi.mcp_app import mcp
from inpi.prazos import _carregar_lote
from inpi.titulares import PROVENIENCIA_CARTEIRA

FONTE = "EPO OPS (INPADOC legal) x base INPI local"


def _membro_ep(membros: list[dict]) -> dict | None:
    """O membro EP representa a familia na consulta de status legal: e nele
    que os escritorios nacionais reportam caducidade/taxa por pais."""
    for mb in membros:
        if mb.get("pais") == "EP":
            return mb
    return None


@mcp.tool()
def carteira_auditoria_vigencia(cliente: str, max_casos: int = 20) -> dict:
    """Audita a vigencia dos casos de um cliente no exterior: para cada caso
    ativo com familia INPADOC, consulta o status legal do membro EP e aponta
    onde a patente CADUCOU (PG25) ou teve taxa paga (PGFP) por pais -- e onde
    a projecao local de anuidade pode estar contando caso morto.

    USE QUANDO: revisar portfolio antes de projetar/faturar anuidade de
    exterior, ou quando o cliente perguntar "onde minha patente ainda vale?".

    Args:
        cliente: nome do titular/cliente.
        max_casos: teto de casos auditados por chamada (quota EPO 4GB/semana).
    """
    from epo.epo_mcp import epo_biblio, epo_status_legal
    from inpi.db import con

    max_casos = max(1, min(max_casos, 100))
    estados, total = _carregar_lote(titular=cliente)
    ativos = [n for n, e in estados.items() if not e["encerrado_em"]]

    auditados, alertas, qualidade, nao_auditados = [], [], [], []
    sem_familia = []
    for num_br in ativos[:max_casos]:
        fam = familia(num_br)
        if fam.get("erro") or not fam.get("membros"):
            sem_familia.append(num_br)
            continue
        membros = fam["membros"]
        ep = _membro_ep(membros)

        # F2: qualidade de cadastro -- titular INPI vs applicant da publicacao
        # EP da mesma familia (epo_biblio, cacheado). So quando ha membro EP.
        if ep:
            tit_inpi = {
                normalizar(r[0]) for r in con().execute(
                    "SELECT DISTINCT depositante FROM depositantes WHERE numero_inpi = ?",
                    [num_br]).fetchall() if r[0]
            }
            bib = epo_biblio(ep["referencia"])
            tit_epo = {
                normalizar(t) for d in bib.get("documentos", [])
                for t in d.get("titulares", []) if t
            }
            if tit_inpi and tit_epo and not (tit_inpi & tit_epo):
                qualidade.append({
                    "numero_inpi": num_br,
                    "titular_inpi": sorted(tit_inpi),
                    "titular_epo": sorted(tit_epo),
                    "nota": ("titular INPI nao bate com o applicant da familia no "
                             "EPO -- confira o cadastro (cessao nao averbada? "
                             "grafia divergente?)"),
                })

        if not ep:
            nao_auditados.append({
                "numero_inpi": num_br,
                "paises": sorted({m["pais"] for m in membros if m.get("pais") not in ("BR", "WO")}),
                "motivo": "sem membro EP -- status legal por pais nao disponivel via INPADOC",
            })
            continue

        st = epo_status_legal(ep["referencia"])
        item = {
            "numero_inpi": num_br,
            "membro_ep": ep["referencia"],
            "caducado_em": st.get("caducado_em", []),
            "taxa_nacional_paga_em": st.get("taxa_nacional_paga_em", []),
            "paises_com_evento": st.get("paises_com_evento_nacional", []),
        }
        auditados.append(item)
        for pais in item["caducado_em"]:
            alertas.append({
                "numero_inpi": num_br,
                "pais": pais,
                "mensagem": (f"INPADOC registra caducidade (PG25) em {pais} para a "
                             f"familia de {num_br} -- nao projete anuidade nesse pais "
                             "sem confirmar com o associado local."),
                "fonte": f"EPO OPS legal, {ep['referencia']}",
            })

    return {
        "cliente": cliente,
        "proveniencia": PROVENIENCIA_CARTEIRA,
        "fonte": FONTE,
        "casos_ativos": len(ativos),
        "casos_auditados": len(auditados),
        "limite_aplicado": max_casos if len(ativos) > max_casos else None,
        "alertas_caducidade": alertas,
        "auditados": auditados,
        "nao_auditados": nao_auditados,
        "sem_familia_consultada": sem_familia,
        "qualidade_dados": qualidade,
        "aviso": (
            "INPADOC e registro do PASSADO: ausencia de evento nao prova "
            "vigencia nem extincao -- pode ser atraso do escritorio nacional. "
            "Membros sem EP nao sao auditaveis por esta rota."
        ),
    }
