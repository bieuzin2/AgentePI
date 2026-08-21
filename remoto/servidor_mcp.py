"""Servidor MCP remoto (streamable HTTP) para o piloto Copilot Studio/Teams --
plano-v2 Fase 6.

Agrega um SUBSET CURADO de tools ja existentes nos servidores stdio locais
(inpi, landscape) num unico FastMCP em transporte HTTP. NAO reimplementa
nenhuma logica -- as funcoes abaixo sao as mesmas ja decoradas com
@mcp.tool() nos servidores locais; aqui so sao reregistradas noutro
`FastMCP` (mcp.add_tool aceita a funcao Python simples).

Auth: chave de API obrigatoria via header. Aceita 'Authorization: Bearer
<chave>' OU 'X-API-Key: <chave>' -- o formulario do Copilot Studio (Fase
6 do plano, GATE VALIDADO) nao documenta qual dos dois usa, entao aceitamos
os dois ate confirmar na conexao real. Sem API_KEY_AGENTE_PI configurada no
ambiente, o servidor RECUSA subir -- nunca fica aberto por engano.

LIMITE CONHECIDO (documentado aqui de proposito, nao escondido): as tools
abaixo dependem de inpi.duckdb/carteira.duckdb/landscape_cache.duckdb locais
e de ADC do Google Cloud -- nenhum dos dois existe no container do Render.
Rodando remoto sem a migracao para MotherDuck (dados) e service account do
BigQuery (landscape), toda tool chamada aqui devolve o RuntimeError claro que
inpi/db.py e landscape/bigquery_client.py ja levantam ("banco ausente" /
"credenciais ausentes") -- nunca falha em silencio, mas tambem nao funciona
ainda. Esse e o proximo passo, nao coberto por este arquivo.

Rode local: PORT=8000 API_KEY_AGENTE_PI=teste python remoto/servidor_mcp.py
"""

from __future__ import annotations

import os


def _materializa_credencial_gcp() -> None:
    """Se GOOGLE_APPLICATION_CREDENTIALS_JSON estiver no ambiente (host que so
    aceita env var, nao arquivo), grava o conteudo num arquivo e aponta o
    GOOGLE_APPLICATION_CREDENTIALS para ele -- e o que a lib do BigQuery espera.

    No Cloud Run isto NAO e necessario: o servico usa a service account de runtime
    (ADC nativo) e o landscape funciona sem env nenhuma. O shim existe para
    portabilidade (Koyeb/VPS/qualquer host sem 'secret file'). Roda antes de
    qualquer import que crie o cliente BigQuery."""
    bruto = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if not bruto or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return
    import tempfile

    caminho = os.path.join(tempfile.gettempdir(), "gcp-creds.json")
    with open(caminho, "w", encoding="utf-8") as fh:
        fh.write(bruto)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = caminho


_materializa_credencial_gcp()

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from epo.epo_mcp import (
    epo_biblio,
    epo_busca,
    epo_familia_inpadoc,
    epo_quota,
    epo_register,
    epo_status_legal,
    epo_texto_integral,
)
from epo.topico import epo_panorama_topico
from inpi.consulta import (
    inpi_busca_ipc,
    inpi_busca_texto,
    inpi_cobertura,
    inpi_despachos_por_rpi,
    inpi_portfolio_titular,
    inpi_processo,
    inpi_titular_resolver,
)
from inpi.inpi_mcp import inpi_citacoes, inpi_reivindicacoes
from inpi.mercado import (
    inpi_carteira,
    inpi_escritorio_resolver,
    inpi_exigencias_escritorio,
)
from inpi.financeiro import financeiro_janelas_desistencia, financeiro_projecao
from inpi.gargalos import inpi_backlog, inpi_pipeline_comparado, inpi_tempo_fases
from inpi.prazos import (
    inpi_anuidades,
    inpi_novidades,
    inpi_prazo_fase_nacional,
    inpi_prazos_carteira,
    inpi_regra_jurisdicao,
)
from inpi.dossie import cliente_dossie
from inpi.fila import fila_semana
from inpi.oposicoes import carteira_oposicoes_ep
from inpi.reconciliacao import reconciliar
from inpi.fto import fto_dominio_publico
from inpi.gaps_protecao import inpi_gaps_protecao
from inpi.inteligencia_mercado import inpi_responsavel_pi
from inpi.anuidades_pagas import inpi_anuidades_pagas
from inpi.peticoes_escritorio import inpi_peticoes_escritorio
from inpi.estatistica import inpi_estatistica
from inpi.exigencias_stats import inpi_exigencias_stats
from inpi.perfil import inpi_perfil_titular
from inpi.radar import inpi_radar
from inpi.saude import carteira_saude
from inpi.vigencia import carteira_auditoria_vigencia
from landscape.carteira_bridge import cpcs_da_carteira, landscape_carteira
from landscape.landscape_mcp import (
    landscape_co_classificacao,
    landscape_evolucao_temporal,
    landscape_perfil_titular,
    landscape_top_titulares,
)

TOOLS = [
    # consulta processual
    inpi_processo, inpi_busca_texto, inpi_busca_ipc, inpi_despachos_por_rpi,
    inpi_titular_resolver, inpi_portfolio_titular, inpi_cobertura,
    # enriquecimento (reivindicacoes/citacoes via Google Patents + familia EPO)
    inpi_reivindicacoes, inpi_citacoes,
    # escritorio: carteira, resolucao de chave e exigencias por periodo
    inpi_escritorio_resolver, inpi_carteira, inpi_exigencias_escritorio,
    # prazos e anuidades
    inpi_anuidades, inpi_prazos_carteira, inpi_regra_jurisdicao,
    inpi_prazo_fase_nacional, inpi_novidades,
    # metricas de negocio (Fase 1-5)
    inpi_tempo_fases, inpi_backlog, inpi_pipeline_comparado,
    financeiro_projecao, financeiro_janelas_desistencia,
    carteira_saude, inpi_radar, inpi_perfil_titular,
    # eficiencia interna (Fases E/F do refinamento)
    carteira_auditoria_vigencia, cliente_dossie, fila_semana,
    carteira_oposicoes_ep,
    # refinamento produto acabado: reconciliacao cross-fonte, FTO/dominio publico,
    # responsavel de PI (curado). busca_anterioridade fica FORA de proposito -- roda
    # 4 fontes em paralelo e pode estourar o timeout ~100s do Copilot Studio.
    reconciliar, fto_dominio_publico, inpi_responsavel_pi, inpi_gaps_protecao,
    inpi_anuidades_pagas, inpi_peticoes_escritorio,
    # inteligencia analitica: motor de estatistica generico + stats de exigencias
    inpi_estatistica, inpi_exigencias_stats,
    # landscape (BigQuery)
    landscape_evolucao_temporal, landscape_top_titulares,
    landscape_co_classificacao, landscape_perfil_titular,
    cpcs_da_carteira, landscape_carteira,
    # EPO OPS (exterior: familias, status legal, texto, register)
    epo_busca, epo_biblio, epo_familia_inpadoc, epo_texto_integral,
    epo_register, epo_status_legal, epo_quota, epo_panorama_topico,
]


def _chave_valida(headers, esperada: str) -> bool:
    """Extrai a chave de 'Authorization: Bearer X' ou 'X-API-Key: X' e compara.
    Funcao pura, sem ASGI -- testavel sem subir servidor."""
    auth = headers.get("authorization", "")
    chave = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else ""
    chave = chave or headers.get("x-api-key", "")
    return bool(esperada) and chave == esperada


class _ExigeChaveDeAPI(BaseHTTPMiddleware):
    """Recusa qualquer request sem a chave certa. '/health' fica de fora --
    e o endpoint que o keep-alive (cron-job.org/UptimeRobot) bate a cada
    poucos minutos para mitigar o cold start do Render free tier."""

    def __init__(self, app, chave_esperada: str):
        super().__init__(app)
        self._chave = chave_esperada

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/health", "/tools"):
            return await call_next(request)
        if not _chave_valida(request.headers, self._chave):
            return JSONResponse({"erro": "chave de API invalida ou ausente"}, status_code=401)
        return await call_next(request)


def montar_app() -> Starlette:
    api_key = os.environ.get("API_KEY_AGENTE_PI")
    if not api_key:
        raise RuntimeError(
            "API_KEY_AGENTE_PI nao configurada -- o servidor remoto nunca sobe "
            "sem chave, para nao ficar aberto por engano. Defina no ambiente "
            "(Render: aba Environment do Web Service)."
        )

    mcp = FastMCP(
        "agente-pi",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        stateless_http=True,
    )
    # Nomes que divergem do __name__ da funcao, para bater com o servidor INPI
    # stdio e com o mapa de roteamento em docs/agente-copilot.md (o Copilot chama
    # a tool pelo nome que o conector expoe -- tem de ser o mesmo em toda parte).
    _NOMES = {"reconciliar": "inpi_reconciliar"}
    for fn in TOOLS:
        mcp.add_tool(fn, name=_NOMES.get(fn.__name__))

    app = mcp.streamable_http_app()
    app.add_middleware(_ExigeChaveDeAPI, chave_esperada=api_key)

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "servidor": "agente-pi", "tools": len(TOOLS)})

    async def tools(request: Request) -> JSONResponse:
        # Nomes das tools que o servidor EXPOE. Sem auth (como /health) -- so nomes,
        # nenhum dado. Serve para conferir num relance, apos um deploy, se uma tool
        # nova chegou ao servidor, e depois comparar com o que o Copilot Studio
        # lista apos o refresh da conexao (ver docs/agente-copilot.md).
        nomes = sorted(_NOMES.get(fn.__name__, fn.__name__) for fn in TOOLS)
        return JSONResponse({"total": len(nomes), "tools": nomes})

    app.add_route("/health", health, methods=["GET"])
    app.add_route("/tools", tools, methods=["GET"])
    return app


app = montar_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
