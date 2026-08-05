"""Servidor MCP sobre a base de dados abertos de patentes do INPI (local, DuckDB).

Por que existe: PPUBS so ve os EUA; o EPO OPS cobre BR pelo INPADOC mas nao tem
texto integral brasileiro nem o historico completo de despachos. Esta camada da
busca em texto de patente BR e o acompanhamento processual, offline e sem
depender da rede do INPI -- que, alias, esta inalcancavel desta maquina
(revistas.inpi.gov.br derruba o handshake TLS; ver inpi/referencias/fontes-rpi.md).

Fonte: https://dadosabertos.inpi.gov.br/index/patentes/ (CSV, atualizado diariamente).
Carregue com:  python inpi/ingest.py

Este arquivo so registra as tools MCP e importa a logica dos modulos abaixo
(modularizacao da Fase 0 -- ver docs/plano-v2.md):
  inpi/db.py       -- conexoes DuckDB
  inpi/consulta.py -- consulta processual (ficha, busca texto/IPC, titulares)
  inpi/prazos.py   -- motor de prazos/anuidades (projecao art. 84, novidades)
  inpi/mercado.py  -- inteligencia de mercado e escritorios
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
    inpi_mercado,
    inpi_prospeccao,
    inpi_serie_mercado,
    inpi_movimentacao_escritorio,
    inpi_transferencias_titular,
    inpi_conflitos_identidade,
    inpi_candidatos_vinculo,
)

RAIZ = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Tools de carteira (thin wrappers, delegam para inpi.carteira)
# ---------------------------------------------------------------------------


@mcp.tool()
def carteira_ingerir(origem: str, cliente: str, mapa: dict | None = None) -> dict:
    """Ingere a lista de casos do escritorio: XLSX, CSV ou lista colada no chat.

    USE QUANDO: o operador mandar a carteira de um cliente, em qualquer formato.
    Passe o caminho do arquivo, ou o proprio texto colado.

    POR QUE ISTO EXISTE: a familia INPADOC NAO ve validacao de patente europeia em
    BE, FR, GB, GR, IE, IT, LU, NL e SE -- o Acordo de Londres dispensa a traducao,
    entao nao ha publicacao nacional e nao existe membro de familia. Num caso real,
    46 de 59 casos eram invisiveis a qualquer busca. A lista do escritorio e a
    unica fonte que enxerga esses casos.

    A saida sempre diz o que NAO entrou: coluna nao reconhecida e linha recusada
    voltam nomeadas. Confira 'aviso' antes de tratar a carteira como completa.

    Args:
        origem: caminho do .xlsx/.csv, ou o texto da lista.
        cliente: nome pelo qual esta carteira sera consultada depois.
        mapa: de-para explicito {rotulo_da_coluna: campo}, quando o cabecalho fugir
            do usual. Campos: jurisdicao, numero_oficial, familia, tipo, data_base,
            data_deposito, data_concessao, data_prioridade, numero_pct, status, nota.
    """
    from inpi import carteira as ct

    return ct.ingerir(origem, cliente=cliente, mapa=mapa)


@mcp.tool()
def carteira_descobrir(cliente: str, titular: str | None = None,
                       expandir_exterior: bool = True, teto: int = 100,
                       descobrir_validacoes_ep: bool = True) -> dict:
    """Levanta a carteira sozinho, pelas tres rotas publicas que existem.

    USE QUANDO: nao houver lista do escritorio, ou para conferir a lista contra o
    que as fontes publicas conhecem. Complementa `carteira_ingerir`, nao substitui.

    AS TRES ROTAS, e o que cada uma so ela ve:
      1. base do INPI       -> os casos brasileiros
      2. familia INPADOC    -> os equivalentes fora da Europa (AU, CA, CN, IN, ZA...)
      3. status legal INPADOC -> as validacoes europeias, INCLUSIVE nos paises do
         Acordo de Londres, que a rota 2 nao enxerga porque la a validacao nao gera
         publicacao nacional. Medido num docketing real: dos 15 estados europeus da
         lista, esta rota achou os 15, e achou um a mais que a lista nao tinha.

    LIMITES: o INPI casa por NOME de depositante, entao grafia variante e titular
    estrangeiro escapam (confira com inpi_titular_resolver); e ausencia de evento no
    status legal pode ser so atraso do escritorio nacional em reportar ao EPO.
    Ausencia aqui nunca e prova de que o caso nao existe.

    'teto' limita as consultas ao EPO. O free tier e 4 GB por semana e a API nao
    expoe contador -- confira com epo_quota. O que ficou de fora volta listado.
    """
    from inpi import carteira as ct

    r = {"descoberta_inpi": ct.descobrir_inpi(cliente, titular=titular)}
    if expandir_exterior:
        r["expansao_exterior"] = ct.expandir_familia(cliente, teto=teto)
    if descobrir_validacoes_ep:
        r["validacoes_europeias"] = ct.descobrir_validacoes(cliente)
    return r


@mcp.tool()
def carteira_listar(cliente: str, jurisdicoes: list[str] | None = None) -> dict:
    """A carteira consolidada de um cliente, com a divergencia entre fontes a vista.

    USE QUANDO: for responder qualquer coisa sobre "os casos do cliente X".

    Um caso que veio de duas fontes e UM caso, com as duas origens declaradas em
    'fontes'. Quando as fontes discordam de data, a linha vem com conflito=true e a
    divergencia detalhada em 'conflitos' -- o valor exibido segue a prioridade
    lista > INPI > EPO Register > INPADOC, mas a escolha nao apaga a divergencia.
    Decidir qual data vale e do procurador.

    Confira sempre 'sem_data_base' e 'carteira_vista_em': caso sem data-base fica
    fora de qualquer projecao de prazo, e carteira antiga envelhece em silencio.
    """
    from inpi import carteira as ct

    return ct.listar(cliente, jurisdicoes=jurisdicoes)


@mcp.tool()
def carteira_validacoes_ep(cliente: str, teto: int = 20) -> dict:
    """Prazo de validacao (art. 65 EPC) e a lacuna do Acordo de Londres, por familia EP.

    USE QUANDO: o cliente tiver patente europeia e a pergunta for "validei onde?" ou
    "qual o prazo para validar?".

    A mencao de concessao vem do European Patent Register -- e dado oficial, e nao
    depende de publicacao nacional. Por isso este e o UNICO prazo dos paises de
    Londres que da para projetar sem a lista do escritorio.

    'estados_de_londres_sem_registro' e a pergunta que so o associado responde: em
    BE, FR, GB, GR, IE, IT, LU, NL e SE a validacao nao gera publicacao nacional, e
    nenhuma fonte publica registra que ela ocorreu. Uma linha por familia, nunca uma
    por estado designado -- o deposito designa ~39 estados de uma vez, e trata-los
    como carteira inventaria 39 casos por patente.

    O prazo de 3 meses e REGRA NAO REVISADA: ha estados com regime proprio e com
    traducao parcial. Confirme com o associado.
    """
    from inpi import carteira as ct

    return ct.validacoes_ep(cliente, teto=teto)


@mcp.tool()
def carteira_panorama(cliente: str, de: str | None = None, ate: str | None = None,
                      jurisdicoes: list[str] | None = None,
                      incluir_validacao_ep: bool = True) -> dict:
    """TODOS os prazos de um cliente: Brasil e exterior, pais grande e pais pequeno.

    USE QUANDO: a pergunta for "quais os prazos do cliente X". E a porta de entrada:
    uma chamada devolve anuidade brasileira, anuidade estrangeira e prazo de
    validacao de EP, ja ordenados por data.

    Depende da carteira estar carregada -- rode antes `carteira_ingerir` (lista do
    escritorio) e/ou `carteira_descobrir` (base do INPI + familia INPADOC).

    LEIA 'lacunas' SEMPRE, e reproduza na resposta ao operador. Ela diz o que este
    quadro NAO cobre: casos sem data-base, jurisdicao fora da tabela de regras,
    jurisdicao com regra nao revisada, divergencia entre fontes, validacao europeia
    possivelmente invisivel e a idade da carteira. Um quadro sem as lacunas a vista
    parece completo, e nao e.

    A coluna 'confianca' nao e decorativa: 'calculado' e o art. 84 brasileiro,
    calibrado contra 285.409 despachos; 'estimado' e regra estrangeira transcrita da
    legislacao, sem revisao de profissional habilitado. Nunca apresente 'estimado'
    como prazo confirmado.

    Args:
        de: inicio da janela (AAAA-MM-DD). Padrao: hoje.
        ate: fim da janela. Padrao: um ano a frente.
        incluir_validacao_ep: consulta o European Patent Register. Custa cota do EPO
            (4 GB/semana, sem contador na API); desligue em consulta exploratoria.
    """
    from inpi import carteira as ct

    return ct.panorama(cliente, de=de, ate=ate, jurisdicoes=jurisdicoes,
                       incluir_validacao_ep=incluir_validacao_ep)


@mcp.tool()
def carteira_jurisdicoes_a_revisar(cliente: str | None = None) -> dict:
    """Fila de jurisdicoes a assinar, ordenada pelo peso na carteira do cliente.

    USE QUANDO: o operador perguntar por que uma data saiu como 'estimado', ou quiser
    saber onde investir o esforco de revisao.

    Hoje so o Brasil projeta com rotulo 'calculado' -- a regra do art. 84 foi
    calibrada contra 285.409 despachos desta base. As demais sao transcricao de
    legislacao, sem nada nos dados que as confirme.

    Ordenar pela carteira real e o ponto: numa carteira de 59 casos, assinar SO a
    linha 'EP-nac' converte 30 deles. Cada item traz a regra atual, a base legal e as
    quatro perguntas que decidem. Assinar = preencher 'revisado_por' e 'revisado_em'
    em inpi/referencias/anuidades-por-jurisdicao.csv; nao ha codigo a mudar.

    Isto e insumo de revisao, nao revisao: quem assina e profissional habilitado.
    """
    from inpi import carteira as ct

    return ct.a_revisar(cliente)


# ---------------------------------------------------------------------------
# Alertas da vigilancia autonoma (vigilancia/executar.py alimenta esta base)
# ---------------------------------------------------------------------------


@mcp.tool()
def inpi_alertas(apenas_nao_vistos: bool = True, severidade: str | None = None,
                 limite: int = 100, marcar_vistos: list[int] | None = None) -> dict:
    """Le os alertas gerados pela vigilancia autonoma (vigilancia/executar.py).

    USE QUANDO: o operador perguntar "o que mudou desde a ultima vez" ou "tem
    alerta pendente". Os alertas vem da execucao agendada semanal (terca 20h,
    pos-RPI) -- watchlist de carteira, concorrentes, IPC, anuidades e (mensal)
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
