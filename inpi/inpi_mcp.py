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
    inpi_producao_escritorio,
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

# Tools novas (refinamento): responsavel_pi ja e decorada no proprio modulo (basta
# importar para registrar). reconciliar/fto sao logica pura -- registramos aqui com
# nome agent-facing, mantendo o modulo livre de dependencia do servidor.
from inpi.inteligencia_mercado import inpi_responsavel_pi  # noqa: F401
from inpi.anuidades_pagas import inpi_anuidades_pagas  # noqa: F401
from inpi.peticoes_escritorio import inpi_peticoes_escritorio  # noqa: F401
from inpi.estatistica_nacional import inpi_estatistica_nacional  # noqa: F401
from inpi.benchmark_mercado import inpi_benchmark_mercado  # noqa: F401
# estatistica/exigencias_stats sao logica pura (sem @mcp.tool no modulo) -- registra aqui.
from inpi.estatistica import inpi_estatistica as _inpi_estatistica
from inpi.exigencias_stats import inpi_exigencias_stats as _inpi_exigencias_stats

mcp.tool(name="inpi_estatistica")(_inpi_estatistica)
mcp.tool(name="inpi_exigencias_stats")(_inpi_exigencias_stats)
from inpi.reconciliacao import reconciliar as _reconciliar
from inpi.fto import fto_dominio_publico as _fto_dominio_publico
from inpi.gaps_protecao import inpi_gaps_protecao as _inpi_gaps_protecao

mcp.tool(name="inpi_reconciliar")(_reconciliar)
mcp.tool(name="fto_dominio_publico")(_fto_dominio_publico)
mcp.tool(name="inpi_gaps_protecao")(_inpi_gaps_protecao)

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
    """Quadro reivindicatorio de um documento BR, US, EP ou WO, via texto
    integral (Google Patents / EPO OPS, conforme a jurisdicao) -- com
    fallback pro PDF oficial salvo manualmente quando o documento e BR e
    nenhuma fonte de texto integral o tem.

    USE QUANDO: for montar um claim chart. Cobre as 4 jurisdicoes que mais
    aparecem aqui -- BR, US, EP, WO -- pelo mesmo nome de tool (nao troque
    para outra so por ser US/EP: o roteamento por jurisdicao e automatico,
    pelo prefixo do numero).

    FONTE, por jurisdicao (detectada pelo prefixo do numero normalizado):
    - US: Google Patents (kinds B1/B2/A1/A2). Sem fallback automatico aqui --
      se faltar, tente a tool MCP do USPTO (uspto.ppubs_get_full_document,
      texto integral oficial) antes de declarar ausencia.
    - EP/WO: epo_texto_integral (API oficial do EPO OPS, PRIMARIA para essas
      duas jurisdicoes) -- fallback Google Patents (kinds B1/A1/A2/A3).
    - BR (padrao, sem prefixo): Google Patents (kinds BR) -- fallback familia
      INPADOC + epo_texto_integral de um membro WO/EP -- fallback final PDF
      salvo manualmente em inpi/data/pdfs/{numero_normalizado}.pdf (unico
      caso onde ha PDF; US/EP/WO nao passam por esse fallback). NAO HA
      download automatico confiavel do portal do INPI (busca.inpi.gov.br/pePI
      e stateful, sem endpoint publico estavel por numero -- ver
      docs/aceite/F4-pdf-claimchart.md). BR-only sem familia PCT/WO/EP
      publicada pode nao ter texto integral em NENHUMA fonte automatica --
      isso e limite de cobertura da fonte, nao erro desta tool; so o PDF
      manual resolve.

    Aceita os mesmos formatos de numero que inpi_processo (BR) ou o numero de
    publicacao com prefixo do pais (US/EP/WO, ex.: 'US6421675B1', 'EP1234567').

    LEIA 'status'/'mensagem' (fontes de texto integral) ou 'aviso'/
    'secoes_ausentes' (fonte PDF, so BR): 'sem_texto' com mensagem que cita
    'cobertura' e ausencia da fonte, nao falha -- nunca declare "documento nao
    tem reivindicacoes" so porque a busca voltou vazia. Numeracao de
    reivindicacao e heuristica -- confira contra o documento original antes de
    citar em parecer.
    """
    from inpi.consulta import normaliza_numero

    num = normaliza_numero(numero)

    from enriquecimento import harness
    from enriquecimento.fontes.google_patents import detectar_jurisdicao

    enriquecido = harness.enriquecer_claims(num)
    if enriquecido["status"] == "ok":
        return enriquecido

    if detectar_jurisdicao(num) != "BR":
        # Fallback de PDF salvo manualmente so existe para BR (inpi/pdf_inpi.py
        # espera numero de processo INPI, nao publicacao US/EP/WO).
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
