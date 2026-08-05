"""PDF de pedido BR publicado: download best-effort, extracao de texto, parser de secoes.

Por que existe: EPO OPS e PPUBS tem texto integral de EP/US; o BR nao. Sem isto o
claim chart BR nao roda -- a skill analista-patentes-inpi ja suporta US/EP.

DOWNLOAD AUTOMATICO E BEST-EFFORT, NAO GARANTIDO: o portal publico do INPI
(busca.inpi.gov.br/pePI) e uma aplicacao Java stateful -- a busca por numero exige
sessao (JSESSIONID) e um ID interno de pedido (CodPedido) obtido so depois de uma
consulta previa; nao existe endpoint estavel "documento por numero de processo" sem
login. Testado nesta maquina em 2026-08-05: o host responde (200 em
https://busca.inpi.gov.br/pePI/), mas nao ha rota documentada e estavel para obter o
PDF direto por numero. Ver docs/aceite/F4-pdf-claimchart.md para o registro completo.

FALLBACK OBRIGATORIO (e o caminho principal, na pratica): o operador salva o PDF do
processo manualmente em inpi/data/pdfs/{numero_normalizado}.pdf (baixado a mao do
portal). `carregar()` sempre olha essa pasta primeiro.
"""

from __future__ import annotations

import re
from pathlib import Path

from inpi.consulta import normaliza_numero

RAIZ = Path(__file__).resolve().parent
PASTA_PDFS = RAIZ / "data" / "pdfs"

MARCADORES_SECAO = {
    "resumo": re.compile(r"^\s*RESUMO\s*$", re.I | re.M),
    "descritivo": re.compile(
        r"^\s*RELAT[ÓO]RIO\s+DESCRITIVO(?:\s+DA\s+INVEN[ÇC][ÃA]O)?\s*$", re.I | re.M
    ),
    "reivindicacoes": re.compile(r"^\s*REIVINDICA[ÇC][ÕO]ES\s*$", re.I | re.M),
    "desenhos": re.compile(r"^\s*DESENHOS?\s*$", re.I | re.M),
}

_RE_ITEM_REIVINDICACAO = re.compile(r"^\s*(\d{1,3})\s*[.\-–]\s+", re.M)


def caminho_pdf(numero: str) -> Path:
    """Onde o PDF deste processo deveria estar, se salvo manualmente."""
    return PASTA_PDFS / f"{normaliza_numero(numero)}.pdf"


def baixar_pdf(numero: str) -> dict:
    """Tenta baixar o PDF do portal publico do INPI. NAO GARANTIDO -- ver docstring do modulo.

    Nao ha rota publica estavel validada (portal e stateful, exige sessao). Esta
    funcao existe para nao deixar a tentativa automatica sem lugar no codigo, mas
    hoje sempre devolve o fallback manual. Se uma rota estavel for encontrada no
    futuro, implementar aqui sem mudar a assinatura.
    """
    destino = caminho_pdf(numero)
    if destino.exists():
        return {"ok": True, "caminho": str(destino), "origem": "arquivo_local"}
    return {
        "ok": False,
        "caminho_esperado": str(destino),
        "mensagem": (
            "Download automatico do portal do INPI nao disponivel (portal exige "
            "sessao/CodPedido, sem endpoint estavel por numero de processo -- ver "
            "docs/aceite/F4-pdf-claimchart.md). Baixe o PDF manualmente em "
            f"busca.inpi.gov.br/pePI e salve como {destino}"
        ),
    }


def extrair_texto(caminho: Path) -> dict:
    """Texto de um PDF de pedido BR. Declara cobertura -- PDF-imagem nao vira erro silencioso."""
    import pypdf

    leitor = pypdf.PdfReader(str(caminho))
    paginas = [p.extract_text() or "" for p in leitor.pages]
    texto = "\n".join(paginas)
    if not texto.strip():
        return {
            "ok": False,
            "texto": "",
            "paginas": len(paginas),
            "mensagem": (
                "PDF sem texto extraivel (provavelmente digitalizado como imagem). "
                "Requer OCR -- fora de escopo v2.0."
            ),
        }
    return {"ok": True, "texto": texto, "paginas": len(paginas)}


def parse_secoes(texto: str) -> dict:
    """Quebra o texto em resumo / descritivo / reivindicacoes / desenhos por heuristica de marcador.

    Marcadores em maiusculas, cada um em linha propria -- padrao do PDF oficial do
    INPI. Secao ausente no texto fica ausente no resultado (nunca inventada).
    """
    achados = []
    for nome, padrao in MARCADORES_SECAO.items():
        m = padrao.search(texto)
        if m:
            achados.append((m.start(), m.end(), nome))
    achados.sort()

    secoes: dict[str, str] = {}
    for i, (_, fim, nome) in enumerate(achados):
        proximo_inicio = achados[i + 1][0] if i + 1 < len(achados) else len(texto)
        secoes[nome] = texto[fim:proximo_inicio].strip()

    return {
        "secoes_encontradas": [nome for _, _, nome in achados],
        "secoes_ausentes": [n for n in MARCADORES_SECAO if n not in secoes],
        **secoes,
    }


def quadro_reivindicatorio(texto_reivindicacoes: str) -> list[dict]:
    """Reivindicacoes numeradas, uma entrada por item -- formato compativel com o
    claim chart US/EP ja produzido pela skill analista-patentes-inpi (lista de
    {numero, texto})."""
    if not texto_reivindicacoes.strip():
        return []
    marcas = list(_RE_ITEM_REIVINDICACAO.finditer(texto_reivindicacoes))
    if not marcas:
        return [{"numero": None, "texto": texto_reivindicacoes.strip()}]
    itens = []
    for i, m in enumerate(marcas):
        inicio = m.end()
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto_reivindicacoes)
        itens.append({
            "numero": int(m.group(1)),
            "texto": texto_reivindicacoes[inicio:fim].strip(),
        })
    return itens


def carregar(numero: str) -> dict:
    """Pipeline completo: localizar PDF -> extrair texto -> parsear secoes -> quadro de reivindicacoes.

    Fonte primaria e sempre o arquivo local (manual ou baixado); nunca inventa
    conteudo quando o PDF nao existe ou nao tem texto extraivel -- devolve a
    declaracao de cobertura correspondente.
    """
    num = normaliza_numero(numero)
    achado = baixar_pdf(num)
    if not achado["ok"]:
        return {"erro": True, "numero_normalizado": num, **achado}

    ext = extrair_texto(Path(achado["caminho"]))
    if not ext["ok"]:
        return {"erro": True, "numero_normalizado": num, "caminho": achado["caminho"], **ext}

    secoes = parse_secoes(ext["texto"])
    reivindicacoes = quadro_reivindicatorio(secoes.get("reivindicacoes", ""))

    return {
        "erro": False,
        "numero_normalizado": num,
        "caminho": achado["caminho"],
        "paginas": ext["paginas"],
        "secoes_encontradas": secoes["secoes_encontradas"],
        "secoes_ausentes": secoes["secoes_ausentes"],
        "resumo": secoes.get("resumo"),
        "descritivo": secoes.get("descritivo"),
        "reivindicacoes": reivindicacoes,
        "fonte": f"PDF local {achado['caminho']} (origem: {achado.get('origem', 'desconhecida')})",
        "aviso": (
            "Texto extraido mecanicamente de PDF; confira contra o documento oficial "
            "antes de citar em parecer. Numeracao de reivindicacao segue a heuristica "
            "'N.' no inicio de linha -- confira se bate com o original."
        ),
    }
