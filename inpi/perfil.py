"""Perfil analitico de titular: evolucao de depositos por ano, foco tecnologico
e escritorios depositantes -- para QUALQUER titular (cliente ou concorrente),
nao so carteira de cliente (Fase G).

Substitui a lista crua de inpi_portfolio_titular por INTERPRETACAO: tendencia
de deposito ao longo do tempo, tecnologia dominante e quem representa. Toda
contagem grande vem acompanhada da distribuicao por ano que a sustenta -- o
numero seco ('5.244 processos') nao e citavel sozinho, quem le precisa poder
julgar a plausibilidade.

CRUZAMENTO COM BIGQUERY (segunda fonte): acima de LIMIAR_CRUZAMENTO processos,
compara a contagem BR da base INPI com a do mesmo titular no Google Patents
Public Data. IMPORTANTE: o BigQuery casa o nome por STRING EXATA
(assignee_harmonized), nao normalizada -- divergencia de contagem quase sempre
e diferenca de grafia entre as bases, NAO erro de dado. A saida rotula isso
como aproximacao, nunca como confirmacao.

Tudo roda sobre a chave canonica de titular (tabela `titulares`, 3 camadas --
ingest.py::_materializa_titulares), a mesma de inpi_titular_resolver.
"""

from __future__ import annotations

from datetime import date

from inpi.consulta import _linhas, aviso_lag_publicacao
from inpi.mcp_app import mcp
from inpi.titulares import chaves_de, relacionados, resolver

LIMIAR_CRUZAMENTO = 200  # acima disso, cruza com BigQuery como 2a fonte
ANOS_RECENTES = 3        # janela de "escritorios nos ultimos anos"

# Todos os numero_inpi sob uma chave canonica de titular. Subquery reusada em
# cada agregacao -- mesma logica de alvo de inpi_portfolio_titular.
_ALVO = """SELECT DISTINCT dp.numero_inpi
           FROM depositantes dp JOIN titulares t ON t.original = dp.depositante
           WHERE t.chave = ?"""


def _total_processos(chave: str) -> int:
    """Total de processos BR sob a chave -- INCLUI os sem data de deposito, que
    nao entram na evolucao por ano. Sem isto o total bate menos que
    inpi_portfolio_titular e mina a confianca."""
    return _linhas(f"SELECT count(*) n FROM ({_ALVO}) t", [chave])[0]["n"]


def _por_ano(chave: str) -> list[dict]:
    return _linhas(
        f"""SELECT CAST(year(b.data_deposito) AS INT) ano,
                   count(DISTINCT b.numero_inpi) depositos
            FROM biblio b JOIN ({_ALVO}) a USING (numero_inpi)
            WHERE b.data_deposito IS NOT NULL
            GROUP BY 1 ORDER BY 1""",
        [chave],
    )


def _foco_tecnologico(chave: str, limite: int) -> list[dict]:
    return _linhas(
        f"""SELECT substr(i.simbolo, 1, 4) subclasse,
                   count(DISTINCT i.numero_inpi) processos
            FROM ipc i JOIN ({_ALVO}) a USING (numero_inpi)
            WHERE i.simbolo IS NOT NULL AND length(i.simbolo) >= 4
            GROUP BY 1 ORDER BY 2 DESC LIMIT ?""",
        [chave, limite],
    )


def _escritorios(chave: str, limite: int, desde_ano: int | None = None) -> list[dict]:
    filtro = ""
    params: list = [chave]
    if desde_ano is not None:
        filtro = " AND b.data_deposito >= ?"
        params.append(date(desde_ano, 1, 1))
    return _linhas(
        f"""SELECT e.chave escritorio,
                   count(DISTINCT p.numero_inpi) processos
            FROM procuradores p
            JOIN escritorios e ON e.original = p.procurador
            JOIN ({_ALVO}) a ON a.numero_inpi = p.numero_inpi
            JOIN biblio b ON b.numero_inpi = p.numero_inpi
            WHERE 1=1{filtro}
            GROUP BY 1 ORDER BY 2 DESC LIMIT ?""",
        params + [limite],
    )


def _cruzar_bigquery(nome_para_bq: str, contagem_br_inpi: int) -> dict:
    """Segunda fonte: contagem BR do mesmo titular no Google Patents (BigQuery).
    So chamado acima do limiar. Nunca derruba o perfil -- BigQuery indisponivel
    (sem ADC/service account) vira nota, nao erro."""
    try:
        from landscape.landscape_mcp import landscape_perfil_titular

        perfil_bq = landscape_perfil_titular(nome_para_bq)
        br = next((g["depositos"] for g in perfil_bq.get("geografia", [])
                   if g.get("pais") == "BR"), 0)
        return {
            "contagem_br_inpi": contagem_br_inpi,
            "contagem_br_bigquery": br,
            "nome_consultado_no_bigquery": nome_para_bq,
            "aviso": (
                "APROXIMACAO, NAO CONFIRMACAO. O BigQuery casa o nome por string "
                "exata (assignee_harmonized); divergencia entre as duas contagens "
                "quase sempre e diferenca de grafia do titular entre as bases, "
                "nao erro de dado. Use para ordem de grandeza, nunca como numero "
                "oficial. Google Patents tem atraso de meses."
            ),
        }
    except Exception as exc:
        return {
            "contagem_br_inpi": contagem_br_inpi,
            "contagem_br_bigquery": None,
            "nota": (f"Cruzamento com BigQuery indisponivel ({type(exc).__name__}) "
                     "-- perfil segue valido so com a base INPI."),
        }


@mcp.tool()
def inpi_perfil_titular(nome: str, foco_top: int = 8, escritorios_top: int = 5,
                        hoje: str | None = None) -> dict:
    """Perfil analitico de um titular na base BR: evolucao de depositos por ano,
    foco tecnologico (subclasses IPC), e escritorios que o representam --
    incluindo os principais nos ultimos anos, para ver troca de banca.

    USE QUANDO: perguntarem "qual o portfolio/perfil do titular X" e quiser
    INSIGHT, nao lista crua de processos. Serve para cliente e para concorrente
    (inteligencia de mercado). Para a ficha de UM processo especifico, use
    inpi_processo; para a lista de numeros, inpi_portfolio_titular.

    A contagem total sempre vem com a distribuicao por ano que a sustenta.
    Acima de 200 processos, cruza com o Google Patents (BigQuery) como segunda
    fonte de ordem de grandeza -- com aviso de que divergencia pode ser grafia.

    Args:
        nome: parte do nome do titular (case-insensitive).
        foco_top: quantas subclasses IPC no foco tecnologico (1 a 30).
        escritorios_top: quantos escritorios no ranking (1 a 20).
        hoje: 'AAAA-MM-DD' de referencia para a janela "ultimos anos".
    """
    foco_top = max(1, min(foco_top, 30))
    escritorios_top = max(1, min(escritorios_top, 20))
    d_hoje = date.fromisoformat(hoje) if hoje else date.today()

    chaves = chaves_de(nome)
    chave = chaves[0]["chave"] if chaves else None
    if not chave:
        return {
            "nome_consultado": nome,
            "encontrado": False,
            "mensagem": (f"Nenhum titular casou com {nome!r} na base INPI. "
                         "Confira a grafia ou use inpi_titular_resolver."),
        }

    por_ano = _por_ano(chave)
    total = _total_processos(chave)
    com_ano = sum(r["depositos"] for r in por_ano)
    exemplo = next((c["exemplo"] for c in chaves if c["chave"] == chave), nome)

    resultado = {
        "nome_consultado": nome,
        "chave_principal": chave,
        "encontrado": True,
        "normalizacao": resolver(chave),
        "possiveis_relacionados": relacionados(chave),
        "total_processos_br": total,
        "com_data_de_deposito": com_ano,
        "sem_data_de_deposito": total - com_ano,
        "evolucao_por_ano": por_ano,
        "aviso_lag_publicacao": aviso_lag_publicacao(),
        "foco_tecnologico": _foco_tecnologico(chave, foco_top),
        "escritorios": _escritorios(chave, escritorios_top),
        "escritorios_ultimos_anos": _escritorios(
            chave, escritorios_top, desde_ano=d_hoje.year - ANOS_RECENTES),
        "outras_chaves_no_nome": [
            {"chave": c["chave"], "processos": c["processos"], "exemplo": c["exemplo"]}
            for c in chaves if c["chave"] != chave
        ],
        "fonte": "base INPI local (depositantes/biblio/ipc/procuradores)",
        "nota": (
            "Distribuicao por ano acompanha a contagem de proposito: o total "
            "sozinho nao e citavel. 'total_processos_br' inclui os "
            "'sem_data_de_deposito', que NAO aparecem em 'evolucao_por_ano' -- "
            "por isso a soma dos anos pode dar menos que o total. "
            "'outras_chaves_no_nome' sao grupos economicos/homonimos que casaram "
            "o texto mas NAO estao somados no total -- confira antes de juntar."
        ),
    }

    if total >= LIMIAR_CRUZAMENTO:
        resultado["cruzamento_bigquery"] = _cruzar_bigquery(exemplo, total)

    return resultado


def demo() -> None:
    """Self-check sem rede: exige inpi.duckdb local. Roda so se o banco existir."""
    from inpi.db import BANCO
    if not BANCO.exists():
        print("SKIP  inpi.duckdb ausente")
        return
    r = inpi_perfil_titular("Petrobras")
    assert r["encontrado"] and r["total_processos_br"] > 0
    assert r["com_data_de_deposito"] == sum(a["depositos"] for a in r["evolucao_por_ano"])
    assert r["total_processos_br"] == r["com_data_de_deposito"] + r["sem_data_de_deposito"]
    print(f"OK  perfil Petrobras: {r['total_processos_br']} processos, "
          f"{len(r['evolucao_por_ano'])} anos, top IPC "
          f"{[f['subclasse'] for f in r['foco_tecnologico'][:3]]}")


if __name__ == "__main__":
    demo()
