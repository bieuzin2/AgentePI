"""Coleta de campos que so existem na ficha do pePI, nao no dump de dados
abertos: CPC, historico de Peticoes/Servicos e ledger de Anuidades.

Confirmado ao vivo em 2026-08-11, comparando fichas reais (pedido moderno
publicado, pedido em sigilo, pedido antigo formato PIxxxx concedido ha 20
anos) contra as colunas dos CSVs (biblio/conteudo/depositantes/inventores/
procuradores/ipc/despachos/prioridades): titulo, resumo, IPC, inventor,
depositante, datas, despacho, procurador e prioridade unionista ja vem do
dump -- nao raspar de novo. Data de Concessao (campo 47) tambem nao precisa:
da pra derivar de despachos.codigo_despacho LIKE '16.%' + data_rpi, sem rede.

Link de "Documentos Publicados" fica de fora por ora: nao e um <a href> direto,
e um visualizador via javascript:EnableHide('PatentDocument') -- o endpoint
por tras fica pro piloto investigar, best-effort (ver
scripts/coleta_ficha_extras_piloto.py). Se nao resolver rapido, fica pra
trabalho futuro junto com PDF completo/reivindicacoes.

Reaproveita a sessao/paralelismo/formato de numero de inpi.coleta_sigilo
(_Trabalhador.ficha_html, _formatar_numero_busca) -- so troca o parser: o
campo (74) da Frente 2 e um valor unico, mas Anuidades/Peticoes tem estrutura
de tabela repetida e variavel (uma tabela HTML por anuidade; uma linha de
tabela por peticao), entao regex sobre HTML cru quebraria em silencio. Usa
BeautifulSoup (ja e dependencia instalada -- bs4) pra navegar a estrutura, e
regex so sobre o texto ja linearizado de cada bloco encontrado.
"""

from __future__ import annotations

import csv
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

from inpi.coleta_sigilo import CircuitBreaker, _abrir_trabalhadores, _com_timeout_forte, _Trabalhador
from inpi.db import con

RAIZ = Path(__file__).resolve().parent
CSV_FICHA_EXTRAS = RAIZ / "referencias" / "ficha-extras.csv"
CAMPOS = ["numero_inpi", "cpc", "peticoes_json", "anuidades_json",
          "link_documento", "escritorio_canonico", "fonte", "coletado_em"]

_RE_PETICAO_ROW = re.compile(
    r"^(?P<codigo>\d+)\|Descri.{1,3}o do Servi.o\|\d+\|(?P<descricao>.*?)\|"
    r"Informa.{1,3}es do Banco:\|(?P<banco>.*?)\|Data:\s*(?P<data_pagamento>\d{2}/\d{2}/\d{4})\|"
    r"Valor: R\$(?P<valor>[\d.,]+)\|(?P<protocolo>\d+)\|(?P<data_protocolo>\d{2}/\d{2}/\d{4})"
)


def campo_por_codigo(soup: BeautifulSoup, codigo: str) -> str | None:
    """Le o valor de um campo numerado da ficha (ex.: '(52)' pra CPC, '(51)'
    pra IPC) pela estrutura HTML: acha o <font class="alerta"> com o codigo,
    sobe pro <tr>, pega o <td> irmao com o valor. Generico o bastante pra
    aguentar tanto campo com <a> (CPC/IPC, com tooltip de descricao) quanto
    campo com texto simples -- estrutural, nao regex sobre HTML cru, porque a
    marcacao ao redor do valor varia por campo."""
    marcador = soup.find("font", class_="alerta", string=lambda s: s and s.strip() == codigo)
    if marcador is None:
        return None
    tr = marcador.find_parent("tr")
    if tr is None:
        return None
    tds = tr.find_all("td", recursive=False)
    if len(tds) < 2:
        return None
    valor_td = tds[1]
    links = [a.get_text(strip=True) for a in valor_td.find_all("a", class_="normal")]
    if links:
        return "; ".join(dict.fromkeys(links)) or None
    texto = valor_td.get_text(separator=" ", strip=True)
    return texto or None


def _extrair_anuidades(soup: BeautifulSoup) -> list[dict]:
    """Cada anuidade e uma <table> pequena, cujo primeiro <td> tem um <span>
    com 'anuidade' e a segunda linha traz Status/GRU/Valor/Data Pagamento. A
    mesma anuidade aparece duas vezes na ficha (resumo das 3 mais recentes +
    lista completa) -- dedup por numero, mantendo a primeira ocorrencia."""
    vistas: dict[str, dict] = {}
    for tab in soup.find_all("table"):
        primeira_td = tab.find("td")
        if primeira_td is None:
            continue
        span = primeira_td.find("span")
        if span is None or "anuidade" not in span.get_text(strip=True).lower():
            continue
        texto = tab.get_text(separator="|", strip=True)
        if "Status:" not in texto:
            continue
        m = re.match(r"^(\d+)\|", texto)
        if not m:
            continue
        numero = m.group(1)
        if numero in vistas:
            continue
        item: dict = {"numero": numero}
        ms = re.search(r"Status:\|([^|]+)", texto)
        item["status"] = ms.group(1).strip() if ms else None
        mg = re.search(r"GRU:\|([^|]+)", texto)
        if mg:
            item["gru"] = mg.group(1).strip()
        mv = re.search(r"Valor: R\$\|([^|]+)", texto)
        if mv:
            item["valor"] = mv.group(1).strip()
        md = re.search(r"Data Pagamento:\|([^|]+)", texto)
        if md:
            item["data_pagamento"] = md.group(1).strip()
        vistas[numero] = item
    return [vistas[k] for k in sorted(vistas, key=int)]


def _extrair_peticoes(soup: BeautifulSoup) -> list[dict]:
    """A tabela de Peticoes/Servicos e identificada pelo <thead> com
    'Protocolo' no cabecalho; cada linha de dado tem class="normal". Linhas
    fora do padrao esperado (ex.: com observacao extra) sao puladas, nao
    travam a extracao -- best-effort, o piloto mede quantas linhas escapam."""
    tabela = None
    for tab in soup.find_all("table"):
        thead = tab.find("thead", recursive=False)
        if thead and "protocolo" in thead.get_text(strip=True).lower():
            tabela = tab
            break
    if tabela is None:
        return []
    tbody = tabela.find("tbody", recursive=False)
    if tbody is None:
        return []
    itens = []
    for row in tbody.find_all("tr", recursive=False):
        if "normal" not in (row.get("class") or []):
            continue
        texto = row.get_text(separator="|", strip=True)
        m = _RE_PETICAO_ROW.match(texto)
        if not m:
            continue
        item = {k: v.strip() for k, v in m.groupdict().items()}
        itens.append(item)
    return itens


def _soup(html: str) -> BeautifulSoup:
    """lxml (parser em C) em vez de html.parser (Python puro): fichas antigas
    tem 250KB e 70+ tabelas de anuidade, e o parse dominava o custo por pedido.
    Sob paralelismo alto o parse em Python puro ainda segura o GIL e serializa
    as threads -- mais workers ficavam MAIS lentos. lxml e ~10-20x mais rapido
    e solta o GIL durante o parse. Fallback pra html.parser se lxml faltar."""
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def extrair_campos(html: str) -> dict:
    """Extrai CPC, peticoes e anuidades do HTML da ficha. Cada chave pode vir
    vazia/None -- ausencia e dado real (pedido sem anuidade paga ainda, sem
    CPC atribuido), nao falha de parser."""
    soup = _soup(html)
    return {
        "cpc": campo_por_codigo(soup, "(52)"),
        "peticoes": _extrair_peticoes(soup),
        "anuidades": _extrair_anuidades(soup),
    }


_cache_coletados: set[str] | None = None


def _coletados() -> set[str]:
    """Set em memoria dos numero_inpi ja no CSV curado, carregado uma vez.
    registrar() relendo o CSV inteiro (csv.DictReader) a cada chamada virou
    O(n) por gravacao sob o lock global dos drivers paralelos -- medido em
    producao com 15851 linhas: 737ms por leitura, ou seja TODOS os workers
    parados quase 3/4 de segundo a cada registro. Piora sozinho conforme o
    CSV cresce (O(n^2) na rodada inteira). Cache resolve: le uma vez, atualiza
    em memoria a cada gravacao. Seguro sem lock proprio porque registrar() so
    e chamado sob o lock do driver (varrer_e_registrar_paralelo) -- 1 chamada
    por vez."""
    global _cache_coletados
    if _cache_coletados is None:
        _cache_coletados = {r["numero_inpi"] for r in _le_csv()}
    return _cache_coletados


def registrar(
    numero_inpi: str,
    campos: dict,
    escritorio_canonico: str,
    fonte: str,
    coletado_em: str,
    link_documento: str = "",
    atualizar: bool = False,
) -> bool:
    """Grava uma linha coletada no CSV curado. Recusa (devolve False) quando
    o numero_inpi nao existe na base ou ja foi coletado -- mesmo espirito de
    inpi.coleta_sigilo.registrar.

    `atualizar=True` (recoleta incremental, vigilancia.incremento_plataforma_nova)
    dispensa a recusa por "ja coletado": APENDA uma linha nova com o
    coletado_em de hoje. O CSV e append-only de proposito (609MB, reescrever
    uma linha no meio custaria uma passada inteira a cada gravacao); quem
    resolve a duplicata e inpi.ingest._mescla_ficha_extras, que mantem so a
    linha mais recente por numero_inpi. Sem isto o watermark de
    numeros_watermark_vencido() nunca avanca."""
    c = con()
    existe = c.execute("SELECT 1 FROM biblio WHERE numero_inpi = ?", [numero_inpi]).fetchone()
    if not existe:
        return False

    if not atualizar and numero_inpi in _coletados():
        return False

    novo = not CSV_FICHA_EXTRAS.exists()
    CSV_FICHA_EXTRAS.parent.mkdir(parents=True, exist_ok=True)
    with CSV_FICHA_EXTRAS.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS, lineterminator="\n")
        if novo:
            w.writeheader()
        w.writerow({
            "numero_inpi": numero_inpi,
            "cpc": campos.get("cpc") or "",
            "peticoes_json": json.dumps(campos.get("peticoes") or [], ensure_ascii=False),
            "anuidades_json": json.dumps(campos.get("anuidades") or [], ensure_ascii=False),
            "link_documento": link_documento,
            "escritorio_canonico": escritorio_canonico,
            "fonte": fonte,
            "coletado_em": coletado_em,
        })
    _coletados().add(numero_inpi)
    return True


def _le_csv() -> list[dict]:
    if not CSV_FICHA_EXTRAS.exists():
        return []
    with CSV_FICHA_EXTRAS.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def varrer_e_registrar_paralelo(
    numeros_inpi: list[str], escritorio_canonico: str, paralelismo: int = 4,
    fonte: str = "pePI busca.inpi.gov.br (ficha-extras, paralelo)",
    atualizar: bool = False,
) -> dict:
    """Abre a ficha de cada numero (via _Trabalhador.ficha_html, mesma sessao
    HTTP/paciamento/retry-on-session-loss de inpi.coleta_sigilo) e grava
    CPC/peticoes/anuidades. Nao filtra por escritorio -- quem chama ja decide
    a populacao (ex.: so carteira Clarke) antes de passar numeros_inpi.

    Filtra os ja coletados ANTES do fetch de rede -- registrar() so descartava
    na hora de gravar, entao rodar de novo sobre uma populacao parcialmente
    ja coletada (ex.: retomar apos reiniciar Tor) desperdicava 2 requisicoes
    de rede por numero_inpi so pra jogar o resultado fora no dedup.

    `atualizar=True` desliga esse pre-filtro: a recoleta incremental QUER
    revisitar quem ja foi coletado (e o unico jeito do coletado_em avancar)."""
    if not atualizar:
        numeros_inpi = [n for n in numeros_inpi if n not in _coletados()]
    trabalhadores = _abrir_trabalhadores(paralelismo)
    if trabalhadores is None:
        return {"erro": "nao foi possivel abrir sessao anonima no pePI"}

    lock = threading.Lock()
    quebrador = CircuitBreaker()
    resumo = {"registrados": 0, "nao_encontrado": 0, "ja_coletado_ou_invalido": 0}
    progresso = {"n": 0, "t0": time.monotonic()}

    def _processar(numero_inpi: str) -> None:
        trabalhador = trabalhadores.get()
        try:
            html = _com_timeout_forte(lambda: trabalhador.ficha_html(numero_inpi))
            if html is None:
                trabalhador.renovar()
        finally:
            trabalhadores.put(trabalhador)
        with lock:
            progresso["n"] += 1
            if progresso["n"] % 200 == 0:
                dt = time.monotonic() - progresso["t0"]
                print(f"  progresso: {progresso['n']} fichas, "
                      f"{progresso['n']/dt*60:.0f} fichas/min, "
                      f"{resumo['registrados']} gravados", flush=True)
        if html is None:
            quebrador.falha()
            with lock:
                resumo["nao_encontrado"] += 1
            return
        quebrador.sucesso()
        campos = extrair_campos(html)
        with lock:
            ok = registrar(numero_inpi, campos, escritorio_canonico, fonte,
                           date.today().isoformat(), atualizar=atualizar)
            resumo["registrados" if ok else "ja_coletado_ou_invalido"] += 1

    with ThreadPoolExecutor(max_workers=paralelismo) as ex:
        futuros = [ex.submit(_processar, n) for n in numeros_inpi]
        for f in as_completed(futuros):
            f.result()
    return resumo
