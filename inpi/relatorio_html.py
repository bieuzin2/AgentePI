"""Render do panorama da carteira em UM HTML autocontido (interativo + print A4).

Consome inpi.painel_dados.montar() (camada de dados unica, Fase 2 -- plano
4.3) e emite um arquivo unico:
  - Chart.js vendorizado inline (offline, sem CDN)
  - dados embutidos como JSON
  - segmentacao global (refiltra o relatorio inteiro) + AutoFilter estilo Excel
  - secoes novas: alertas da semana, anuidades 90 dias, tarefas (placeholder),
    landscape (placeholder) -- renderizadas em Python, estaticas (nao entram
    na segmentacao client-side: sao snapshot do dia, nao dimensao do caso)
  - @media print A4, tema claro forcado

Design validado com ui-ux-pro-max: estilo Data-Dense Dashboard, paleta oficial
ClarkeModet extraida do site (azul royal #0033FF + magenta #FF0066), logo SVG
oficial embutido, WCAG AA. Fontes: stack de sistema (a marca usa FS Emeric, custom
paga -- nao embutivel; o "cara" da marca vem do logo + cores).

CSS e JS ficam em relatorio_html_css.py / relatorio_html_js.py (arquivo unico
passava de 500 linhas -- regra do projeto).

Uso:
    from inpi.relatorio_html import gerar
    gerar()  # Clarke Modet, saida padrao em docs/relatorios/
"""

from __future__ import annotations

import base64
import html
import json
from datetime import date
from pathlib import Path

from inpi import painel_dados
from inpi.relatorio_html_css import CSS
from inpi.relatorio_html_js import _JS

RAIZ = Path(__file__).resolve().parent
VENDOR_CHART = RAIZ / "referencias" / "chart.umd.min.js"
LOGO_OFICIAL = RAIZ / "referencias" / "marca-clarkemodet" / "logo-clarkemodet-blue.svg"
FONTS_DIR = RAIZ / "referencias" / "fonts"

_SEVERIDADE_ROTULO = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}


def _logo() -> str:
    """Logo oficial da ClarkeModet (SVG, extraido do site), embutido inline."""
    svg = LOGO_OFICIAL.read_text(encoding="utf-8")
    return svg[svg.index("<svg"):]  # tira o <?xml ?> prolog


def _fontes() -> str:
    """@font-face da Inter, woff2 embutido em base64 (offline, sem CDN)."""
    faces = []
    for peso in (400, 500, 600, 700):
        f = FONTS_DIR / f"inter-{peso}.woff2"
        b64 = base64.b64encode(f.read_bytes()).decode()
        faces.append(
            "@font-face{font-family:'Inter';font-style:normal;font-weight:%d;"
            "font-display:swap;src:url(data:font/woff2;base64,%s) format('woff2')}"
            % (peso, b64)
        )
    return "".join(faces)


def _fmt(n) -> str:
    return f"{n:,}".replace(",", ".") if isinstance(n, int) else str(n)


def _esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def _secao_alertas(alertas: list[dict]) -> str:
    """Alertas da semana -- ultimos gravados por vigilancia/executar.py."""
    if not alertas:
        corpo = ('<tr><td colspan="5">Nenhum alerta registrado ainda '
                 '(a vigilância autônoma ainda não rodou, ou não há novidade).</td></tr>')
    else:
        linhas = []
        for a in alertas[:20]:
            sev = a.get("severidade") or "baixa"
            tag = f'<span class="tag {_esc(sev)}">{_esc(_SEVERIDADE_ROTULO.get(sev, sev))}</span>'
            alvo = a.get("processo") or a.get("titular") or "-"
            linhas.append(
                f"<tr><td>{tag}</td><td>{_esc(alvo)}</td><td>{_esc(a.get('tipo'))}</td>"
                f"<td>{_esc((a.get('mensagem') or '')[:220])}</td>"
                f"<td>{_esc(a.get('data') or '-')}</td></tr>"
            )
        corpo = "".join(linhas)
    return f"""<section><h2>Alertas da semana</h2>
  <p class="sub">Últimos alertas gravados pela vigilância autônoma (vigilancia/executar.py) --
    despachos novos, anulações, concorrentes, IPC vigiada, anuidades e status legal exterior.</p>
  <div style="overflow-x:auto"><table><thead><tr><th>Severidade</th>
    <th>Processo/titular</th><th>Tipo</th><th>Mensagem</th><th>Data</th></tr></thead>
    <tbody>{corpo}</tbody></table></div></section>"""


def _secao_anuidades_90d(anuidades: list[dict]) -> str:
    """Anuidades entrando na janela de 90 dias -- recorte do prazos_12m do panorama."""
    if not anuidades:
        corpo = '<tr><td colspan="4">Nenhuma anuidade na janela de 90 dias.</td></tr>'
    else:
        corpo = "".join(
            f"<tr><td>{_esc(p['numero_inpi'])}</td><td>{_esc(p.get('cliente') or '-')}</td>"
            f"<td>{_esc(p['descricao'])}</td><td>{_esc(p['prazo'])}</td></tr>"
            for p in anuidades
        )
    return f"""<section><h2>Anuidades — próximos 90 dias</h2>
  <p class="sub">Projeção art. 84 LPI. Anuidade <b>notificada</b>, não paga -- confira no
    controle de prazos antes de agir.</p>
  <div style="overflow-x:auto"><table><thead><tr><th>Processo</th><th>Cliente</th>
    <th>Descrição</th><th>Prazo</th></tr></thead><tbody>{corpo}</tbody></table></div></section>"""


def _secao_placeholder(titulo: str, nota: str) -> str:
    """Secao de feature ainda nao implementada (Fases 5/6). Le como 'em construcao'."""
    return f"""<section><h2>{_esc(titulo)}</h2>
  <div class="placeholder"><b>Ainda não implementado</b>{_esc(nota)}</div></section>"""


def gerar(procurador: str = "Clarke Modet", hoje: str | None = None,
          saida: str | None = None, banco_alertas: str | None = None) -> dict:
    ref = hoje or date.today().isoformat()
    d = painel_dados.montar(procurador, hoje=ref,
                             banco_alertas=Path(banco_alertas) if banco_alertas else None)
    dados = json.dumps(d, ensure_ascii=False, default=str)
    chart_js = VENDOR_CHART.read_text(encoding="utf-8")

    cob = d["cobertura"]
    alerta = cob.get("ALERTA_BASE_DESATUALIZADA")
    cob_html = (
        f'Base INPI até RPI {cob["ultimo_numero_rpi"]} '
        f'({cob["ultima_rpi"]}) · {_fmt(cob["despachos"])} despachos'
        + (f'<br><span class="alerta">⚠ {cob["dias_desde_a_ultima_rpi_carregada"]} '
           f'dias desde a última RPI</span>' if alerta else '')
    )

    secoes_novas = (
        _secao_alertas(d["alertas_semana"])
        + _secao_anuidades_90d(d["anuidades_90d"])
        + _secao_placeholder("Tarefas abertas", d["tarefas"]["nota"])
        + _secao_placeholder("Landscape (panorama de mercado)", d["landscape"]["nota"])
    )

    html_out = _TEMPLATE.format(
        css=_fontes() + CSS, logo=_logo(), titulo="Panorama da Carteira",
        escritorio=procurador, cobertura=cob_html,
        gerado=date.fromisoformat(ref).strftime("%d/%m/%Y"),
        dados=dados, chartjs=chart_js, js=_JS, secoes_novas=secoes_novas,
    )

    destino = Path(saida) if saida else (
        RAIZ.parent / "docs" / "relatorios" /
        f"panorama_{procurador.lower().replace(' ', '_')}.html"
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(html_out, encoding="utf-8")
    return {"arquivo": str(destino), "tamanho_mb": round(len(html_out) / 1e6, 2),
            "total_casos": d["total_casos"]}


_TEMPLATE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{titulo} — {escritorio}</title>
<style>{css}</style></head><body>
<header class="top"><div class="top-in">
  {logo}<h1>{titulo}</h1>
  <div class="cobertura">{cobertura}<br>gerado em {gerado}</div>
</div></header>
<div class="wrap">
  <div class="seg" id="seg"></div>
  <div class="print-recorte" id="printRecorte"></div>
  <div class="recorte" id="recorte"></div>
  <div class="kpis" id="kpis"></div>
  <div id="secoes"></div>
  {secoes_novas}
  <footer>
    <span>Relatório extraído por <b>gcunha</b> · agente de patentes</span>
    <span>Projeção calculada sob a LPI — não substitui o docketing. Anuidade
      notificada, não paga.</span>
  </footer>
</div>
<script>{chartjs}</script>
<script>const DATA={dados};</script>
<script>{js}</script>
</body></html>"""


if __name__ == "__main__":
    print(gerar(hoje="2026-08-05"))
