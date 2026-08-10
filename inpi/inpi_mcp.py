"""Servidor MCP sobre a base de dados abertos de patentes do INPI (local, DuckDB).

Por que existe: PPUBS so ve os EUA; o EPO OPS cobre BR pelo INPADOC mas nao tem
texto integral brasileiro nem o historico completo de despachos. Esta camada da
busca em texto de patente BR e o acompanhamento processual, offline e sem
depender da rede do INPI -- que, alias, esta inalcancavel desta maquina
(revistas.inpi.gov.br derruba o handshake TLS; ver inpi/referencias/fontes-rpi.md).

Fonte: https://dadosabertos.inpi.gov.br/index/patentes/ (CSV, atualizado semanalmente, aos sabados).
Carregue com:  python inpi/ingest.py

Este arquivo so registra as tools MCP e importa a logica dos modulos abaixo
(modularizacao da Fase 0 -- ver docs/plano-v2.md):
  inpi/db.py       -- conexoes DuckDB
  inpi/consulta.py -- consulta processual (ficha, busca texto/IPC, titulares)
  inpi/prazos.py   -- motor de prazos/anuidades (projecao art. 84, novidades)
  inpi/mercado.py  -- inteligencia de mercado e escritorios
  inpi/gargalos.py -- tempo por fase do exame, backlog e comparativo de pipeline
  inpi/financeiro.py -- projecao de anuidades por mes/pais e janelas de desistencia
As tools de carteira (thin wrappers sobre inpi/carteira.py) ficam aqui mesmo.
"""

from __future__ import annotations

from pathlib import Path

from inpi.db import BANCO, con
from inpi.mcp_app import mcp

# Reexportados para compatibilidade: testes e panorama_carteira.py referenciam
# estes nomes como atributos de inpi_mcp (m.inpi_processo, m._prazo_declarado...).
from inpi.consulta import (  # noqa: F401
    _anuidades_citadas,
    _linhas,
    _marca_anulacoes,
    _prazo_declarado,
    normaliza_numero,
    inpi_processo,
    inpi_busca_texto,
    inpi_busca_ipc,
    inpi_despachos_por_rpi,
    inpi_titular_resolver,
    inpi_portfolio_titular,
    inpi_cobertura,
)
from inpi.prazos import (  # noqa: F401
    _carregar_lote,
    _estado_de,
    _prazos_de,
    inpi_anuidades,
    inpi_prazos_carteira,
    inpi_relatorio_prazos_pdf,
    inpi_regra_jurisdicao,
    inpi_prazo_fase_nacional,
    inpi_novidades,
)
from inpi.mercado import (  # noqa: F401
    _chave_escritorio,
    inpi_escritorio_resolver,
    inpi_carteira,
    inpi_exigencias_escritorio,
    inpi_mercado,
    inpi_prospeccao,
    inpi_serie_mercado,
    inpi_movimentacao_escritorio,
    inpi_transferencias_titular,
    inpi_conflitos_identidade,
    inpi_candidatos_vinculo,
)
from inpi.gargalos import (  # noqa: F401
    inpi_tempo_fases,
    inpi_backlog,
    inpi_pipeline_comparado,
)
from inpi.financeiro import (  # noqa: F401
    financeiro_projecao,
    financeiro_janelas_desistencia,
)
from inpi.saude import carteira_saude  # noqa: F401
from inpi.radar import inpi_radar  # noqa: F401
from inpi.perfil import inpi_perfil_titular  # noqa: F401
from inpi.vigencia import carteira_auditoria_vigencia  # noqa: F401
from inpi.dossie import cliente_dossie  # noqa: F401
from inpi.fila import fila_semana  # noqa: F401
from inpi.oposicoes import carteira_oposicoes_ep  # noqa: F401

RAIZ = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Tarefas leves (lembretes internos -- plano 4.7. NAO e docketing, sem calculo
# de prazo legal; ver inpi/tarefas.py)
#
# NOTA (Fase G): as tools de "carteira ingerida" (carteira_ingerir/descobrir/
# listar/validacoes_ep/panorama/jurisdicoes_a_revisar) foram REMOVIDAS. Elas
# dependiam de upload manual de portfolio (tabela `casos`), fonte que na pratica
# so tinha um CSV de teste. Tudo agora roda do titular real: inpi_perfil_titular,
# carteira_saude, cliente_dossie, carteira_auditoria_vigencia e
# carteira_oposicoes_ep -- base INPI (BR) + EPO (exterior, inclui Acordo de
# Londres), sem upload.
# ---------------------------------------------------------------------------


@mcp.tool()
def tarefa_criar(descricao: str, processo: str | None = None,
                 prazo_interno: str | None = None) -> dict:
    """Cria um lembrete interno (nao um prazo legal -- isso e docketing, fora daqui).

    USE QUANDO: o operador pedir para anotar algo a fazer, com ou sem processo
    e data associados. 'prazo_interno' e a data que o proprio operador digitou,
    sem regra de LPI por tras -- nao confunda com anuidade/prazo calculado.
    """
    from inpi import tarefas as tf

    return tf.tarefa_criar(descricao, processo=processo, prazo_interno=prazo_interno)


@mcp.tool()
def tarefa_listar(processo: str | None = None, status: str = "aberta") -> dict:
    """Lista tarefas leves. status='todas' traz abertas e concluidas."""
    from inpi import tarefas as tf

    return tf.tarefa_listar(processo=processo, status=status)


@mcp.tool()
def tarefa_concluir(id: int) -> dict:
    """Marca uma tarefa leve como concluida."""
    from inpi import tarefas as tf

    return tf.tarefa_concluir(id)


# ---------------------------------------------------------------------------
# Reivindicacoes de pedido BR publicado (PDF do INPI -- destrava o claim chart BR)
# ---------------------------------------------------------------------------


@mcp.tool()
def inpi_reivindicacoes(numero: str) -> dict:
    """Quadro reivindicatorio de um pedido BR, via texto integral (Google
    Patents / familia INPADOC no EPO) -- com fallback pro PDF oficial salvo
    manualmente quando nenhuma fonte de texto integral tem o documento.

    USE QUANDO: for montar um claim chart de um documento BR (a skill
    analista-patentes-inpi ja suporta US/EP; isto destrava o BR).

    FONTE (nesta ordem):
    1. Google Patents -- serve o texto integral que o INPI/EPO nao tem para
       pedidos depositados so no Brasil (sem passagem PCT/WO). Sem sessao, sem
       captcha, com cache local (ver enriquecimento/).
    2. Familia INPADOC + epo_texto_integral -- quando o Google Patents nao
       acha o documento, tenta o texto integral OFICIAL de um membro WO/EP da
       mesma familia (API do EPO OPS).
    3. PDF salvo manualmente em inpi/data/pdfs/{numero_normalizado}.pdf --
       ultimo recurso. NAO HA download automatico confiavel do portal do INPI
       (busca.inpi.gov.br/pePI e stateful, sem endpoint publico estavel por
       numero -- ver docs/aceite/F4-pdf-claimchart.md).

    Aceita os mesmos formatos de numero que inpi_processo.

    LEIA 'status'/'mensagem' (fontes 1-2) ou 'aviso'/'secoes_ausentes' (fonte
    3, PDF): nenhuma fonte encontrada vira declaracao de cobertura, nunca erro
    silencioso. Numeracao de reivindicacao e heuristica -- confira contra o
    documento original antes de citar em parecer.
    """
    from inpi.consulta import normaliza_numero

    num = normaliza_numero(numero)

    from enriquecimento import harness

    enriquecido = harness.enriquecer_claims(num)
    if enriquecido["status"] == "ok":
        return enriquecido

    from inpi import pdf_inpi

    do_pdf = pdf_inpi.carregar(numero)
    if not do_pdf.get("erro"):
        return do_pdf

    return {
        **enriquecido,
        "tambem_tentado_pdf_local": do_pdf,
    }


@mcp.tool()
def inpi_citacoes(numero: str) -> dict:
    """Documentos citados (citando) e que citam (citada_por) um pedido/patente
    BR, via Google Patents -- o EPO OPS e o PPUBS nao tem essa cobertura para
    BR (PatentsView, a fonte de citacoes do USPTO, foi desligada em mar/2026).

    USE QUANDO: for avaliar o estado da tecnica citado no exame de um processo
    BR, ou mapear quem cita uma patente do cliente.

    Aceita os mesmos formatos de numero que inpi_processo. Lista vazia e um
    resultado valido (documento sem citacao registrada, comum em modelos de
    utilidade) -- leia 'mensagem' para distinguir de falha de busca.
    """
    from inpi.consulta import normaliza_numero
    from enriquecimento import harness

    return harness.enriquecer_citacoes(normaliza_numero(numero))


# ---------------------------------------------------------------------------
# Alertas da vigilancia autonoma (vigilancia/executar.py alimenta esta base)
# ---------------------------------------------------------------------------


@mcp.tool()
def inpi_alertas(apenas_nao_vistos: bool = True, severidade: str | None = None,
                 limite: int = 100, marcar_vistos: list[int] | None = None) -> dict:
    """Le os alertas gerados pela vigilancia autonoma (vigilancia/executar.py).

    USE QUANDO: o operador perguntar "o que mudou desde a ultima vez" ou "tem
    alerta pendente". Os alertas vem da execucao agendada semanal (domingo 08h,
    pos-refresh de sabado dos dados abertos) -- watchlist de carteira,
    concorrentes, IPC, anuidades e (mensal)
    status legal no exterior. Ver vigilancia/vigias.py.

    Passe 'marcar_vistos' com os ids retornados para dar baixa -- proxima
    chamada com apenas_nao_vistos=True nao os traz mais.

    Args:
        apenas_nao_vistos: True (padrao) so mostra o que ainda nao foi marcado.
        severidade: filtra 'alta', 'media' ou 'baixa'. Omita para todas.
        limite: 1 a 500.
        marcar_vistos: lista de ids a marcar como vistos ANTES de listar.
    """
    from vigilancia.executar import BANCO as banco_alertas

    if not banco_alertas.exists():
        return {"erro": True, "mensagem": (
            "vigilancia/data/alertas.duckdb ainda nao existe -- a vigilancia "
            "nunca rodou. Rode 'python -m vigilancia.executar' (ou "
            "--dry-run para testar sem enviar e-mail)."
        )}

    import duckdb

    con = duckdb.connect(str(banco_alertas))
    try:
        if marcar_vistos:
            con.execute(
                f"UPDATE alertas SET visto = TRUE WHERE id IN "
                f"({','.join('?' * len(marcar_vistos))})",
                marcar_vistos,
            )
        cond, params = [], []
        if apenas_nao_vistos:
            cond.append("visto = FALSE")
        if severidade:
            cond.append("severidade = ?")
            params.append(severidade)
        where = (" WHERE " + " AND ".join(cond)) if cond else ""
        params.append(max(1, min(limite, 500)))
        cur = con.execute(
            f"""SELECT id, tipo, severidade, processo, titular, mensagem, data,
                       fonte, data_corte, criado_em, visto
                FROM alertas{where}
                ORDER BY criado_em DESC LIMIT ?""",
            params,
        )
        cols = [d[0] for d in cur.description]
        linhas = [dict(zip(cols, r)) for r in cur.fetchall()]
        total = con.execute("SELECT count(*) FROM alertas").fetchone()[0]
        nao_vistos = con.execute("SELECT count(*) FROM alertas WHERE visto = FALSE").fetchone()[0]
    finally:
        con.close()

    return {
        "total_no_banco": total,
        "nao_vistos": nao_vistos,
        "retornados": len(linhas),
        "marcados_vistos_agora": marcar_vistos or [],
        "alertas": linhas,
        "aviso": (
            "Alertas de vigilancia automatica, sem revisao humana. Confira o "
            "processo original (inpi_processo) antes de agir -- em especial os "
            "de tipo 'anulacao', que revertem um ato anterior."
        ),
    }


if __name__ == "__main__":
    mcp.run()
