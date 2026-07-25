"""Servidor MCP sobre a base de dados abertos de patentes do INPI (local, DuckDB).

Por que existe: PPUBS so ve os EUA; o EPO OPS cobre BR pelo INPADOC mas nao tem
texto integral brasileiro nem o historico completo de despachos. Esta camada da
busca em texto de patente BR e o acompanhamento processual, offline e sem
depender da rede do INPI -- que, alias, esta inalcancavel desta maquina
(revistas.inpi.gov.br derruba o handshake TLS; ver inpi/referencias/fontes-rpi.md).

Fonte: https://dadosabertos.inpi.gov.br/index/patentes/ (CSV, atualizado diariamente).
Carregue com:  python inpi/ingest.py

SOBRE PRAZOS -- leia antes de mexer: este servidor NAO calcula prazo. Medimos:
apenas 1% dos 5,3 milhoes de despachos declaram "N dias" no texto, e "prazo"
aparece em contextos que nao sao prazo. Calcular por analogia entre codigos e
exatamente como se perde direito de terceiro. O servidor devolve o codigo, a
data da RPI e o texto literal publicado; quem conta o prazo e o procurador.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb
from mcp.server.fastmcp import FastMCP

RAIZ = Path(__file__).resolve().parent
BANCO = RAIZ / "data" / "inpi.duckdb"

mcp = FastMCP("inpi")

_con: duckdb.DuckDBPyConnection | None = None


def con() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        if not BANCO.exists():
            raise RuntimeError(
                f"Banco ausente: {BANCO}. Baixe os CSVs de "
                "https://dadosabertos.inpi.gov.br/index/patentes/ para inpi/data/raw/ "
                "e rode: python inpi/ingest.py"
            )
        _con = duckdb.connect(str(BANCO), read_only=True)
    return _con


# "N (por extenso) dias" -- so reconhecemos prazo quando o INPI o escreveu.
_RE_PRAZO = re.compile(r"(\d{1,3})\s*\(\s*[a-zA-ZçÇãáéíóúâêô ]+\s*\)\s*dias", re.I)


def normaliza_numero(bruto: str) -> str:
    """Normaliza qualquer forma usual para a chave do INPI.

    O INPI guarda o moderno com 12 digitos, sem prefixo 'BR' e SEM digito
    verificador ('102022010731'), e o legado como 'PI1107322'. As outras fontes
    entregam diferente: o EPO devolve 'BR-102022010731-A2', e o operador digita
    'BR 10 2022 010731 2' -- a forma impressa, com o verificador no fim.
    """
    s = re.sub(r"[\s.\-/]", "", (bruto or "").upper())
    s = re.sub(r"^BR", "", s)
    s = re.sub(r"[A-Z]\d?$", "", s) if re.match(r"^\d", s) else s  # kind code do EPO
    if re.fullmatch(r"\d{13}", s):  # forma impressa carrega digito verificador
        s = s[:12]
    return s


def _linhas(sql: str, params: list | None = None) -> list[dict[str, Any]]:
    cur = con().execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _prazo_declarado(texto: str | None) -> int | None:
    m = _RE_PRAZO.search(texto or "")
    return int(m.group(1)) if m else None


@mcp.tool()
def inpi_processo(numero: str) -> dict:
    """Ficha completa de um processo brasileiro: dados, partes, IPC e todos os despachos.

    USE QUANDO: precisar do andamento de um pedido BR, do titular real, ou do
    historico processual. E a unica fonte aqui com o historico completo do INPI.

    Aceita 'BR 10 2022 010731 2', 'BR-102022010731-A2' (como o EPO devolve),
    '102022010731' ou 'PI1107322'.
    """
    num = normaliza_numero(numero)
    # ~5 processos em 1 milhao aparecem duas vezes em biblio: uma linha completa e
    # outra so com data_deposito e sigilo. Pegar a primeira que vier devolveria um
    # processo sem data de publicacao -- e a data de publicacao entra no calculo do
    # estado da tecnica. Ordena pela linha mais preenchida.
    bib = _linhas(
        """SELECT * FROM biblio WHERE numero_inpi = ?
           ORDER BY (data_protocolo IS NOT NULL)::INT
                  + (data_publicacao IS NOT NULL)::INT
                  + (numero_pct IS NOT NULL)::INT DESC
           LIMIT 1""",
        [num],
    )
    if not bib:
        return {
            "erro": True,
            "numero_consultado": numero,
            "numero_normalizado": num,
            "mensagem": (
                "Processo nao encontrado na base do INPI. Confira o numero. Lembre "
                "que a base cobre patentes (PI/MU/MI/C/PP) -- marcas e desenhos "
                "industriais estao em outros conjuntos de dados."
            ),
        }

    texto = _linhas("SELECT titulo, resumo FROM conteudo WHERE numero_inpi = ?", [num])
    despachos = _linhas(
        """SELECT numero_rpi, data_rpi, codigo_despacho, complemento_despacho
           FROM despachos WHERE numero_inpi = ? ORDER BY data_rpi, numero_rpi""",
        [num],
    )
    for d in despachos:
        d["prazo_declarado_dias"] = _prazo_declarado(d.get("complemento_despacho"))

    return {
        "numero_inpi": num,
        "dados": bib[0],
        "titulo": (texto[0]["titulo"] if texto else None),
        "resumo": (texto[0]["resumo"] if texto else None),
        "depositantes": _linhas(
            """SELECT ordem, depositante, pais, estado, tipopessoadepositante,
                      data_inicio_depositante, data_fim_depositante
               FROM depositantes WHERE numero_inpi = ? ORDER BY ordem""",
            [num],
        ),
        "inventores": [
            r["autor"]
            for r in _linhas(
                "SELECT autor FROM inventores WHERE numero_inpi = ? ORDER BY ordem",
                [num],
            )
        ],
        # Prioridade unionista (art. 16 da LPI) antecipa a data de corte do estado
        # da tecnica. Sem ela, o confronto usa a data errada e o parecer inteiro cai.
        "prioridades": _linhas(
            """SELECT pais_prioridade, numero_prioridade, data_prioridade
               FROM prioridades WHERE numero_inpi = ? ORDER BY data_prioridade""",
            [num],
        ),
        "procuradores": [
            r["procurador"]
            for r in _linhas(
                """SELECT DISTINCT procurador FROM procuradores
                   WHERE numero_inpi = ? AND procurador IS NOT NULL""",
                [num],
            )
        ],
        "ipc": [
            r["simbolo"]
            for r in _linhas(
                "SELECT simbolo FROM ipc WHERE numero_inpi = ? ORDER BY ordem", [num]
            )
        ],
        "despachos": despachos,
        "ultimo_despacho": despachos[-1] if despachos else None,
        "aviso_prazo": (
            "Os despachos vem com a data da RPI e o texto literal publicado. Este "
            "servidor NAO calcula prazo: 'prazo_declarado_dias' so vem preenchido "
            "quando o proprio INPI escreveu o numero de dias no despacho. Ausencia "
            "significa 'o despacho nao declarou', nunca 'nao ha prazo'. A contagem "
            "e do procurador responsavel."
        ),
    }


@mcp.tool()
def inpi_busca_texto(termos: str, campo: str = "titulo", limite: int = 20,
                     desde: str | None = None) -> dict:
    """Busca patentes brasileiras por texto de titulo ou resumo.

    USE QUANDO: for fazer anterioridade com cobertura Brasil. Nem o PPUBS (so US)
    nem o EPO (que quase nao tem texto integral de BR) cobrem isto -- e a unica
    forma de buscar no texto de patente brasileira neste ambiente.

    Args:
        termos: palavras separadas por espaco; TODAS precisam aparecer (AND).
            Use radical para pegar variacoes: 'biodegrad embalag'.
        campo: 'titulo', 'resumo' ou 'ambos'.
        limite: 1 a 100.
        desde: opcional, 'AAAA-MM-DD' -- filtra por data de deposito.
    """
    limite = max(1, min(limite, 100))
    palavras = [p for p in re.split(r"\s+", termos.strip()) if p]
    if not palavras:
        return {"erro": True, "mensagem": "Informe ao menos um termo."}

    alvo = {
        "titulo": "c.titulo",
        "resumo": "c.resumo",
        "ambos": "coalesce(c.titulo,'') || ' ' || coalesce(c.resumo,'')",
    }.get(campo)
    if not alvo:
        return {"erro": True, "mensagem": "campo deve ser 'titulo', 'resumo' ou 'ambos'."}

    cond = " AND ".join(f"{alvo} ILIKE ?" for _ in palavras)
    params: list = [f"%{p}%" for p in palavras]
    filtro_data = ""
    if desde:
        filtro_data = " AND b.data_deposito >= ?"
        params.append(desde)
    params.append(limite)

    linhas = _linhas(
        f"""SELECT c.numero_inpi, c.titulo, b.data_deposito, b.data_publicacao
            FROM conteudo c LEFT JOIN biblio b USING (numero_inpi)
            WHERE {cond}{filtro_data}
            ORDER BY b.data_deposito DESC NULLS LAST
            LIMIT ?""",
        params,
    )
    return {
        "termos": palavras,
        "campo": campo,
        "retornados": len(linhas),
        "resultados": linhas,
        "nota": (
            "Busca literal por substring (ILIKE), nao semantica: sinonimo nao entra. "
            "Rode tambem por classificacao IPC com inpi_busca_ipc, que independe de "
            "vocabulario, antes de concluir qualquer coisa sobre ausencia de anterioridade."
        ),
    }


@mcp.tool()
def inpi_busca_ipc(simbolo: str, limite: int = 20, desde: str | None = None) -> dict:
    """Busca patentes brasileiras por classificacao IPC.

    USE QUANDO: quiser o angulo imune a vocabulario. Prefixo casa a subclasse
    inteira: 'B65D 65/46' e exato; 'B65D 65' pega o grupo; 'B65D' pega a subclasse.
    """
    limite = max(1, min(limite, 100))
    params: list = [f"{simbolo.strip()}%"]
    filtro = ""
    if desde:
        filtro = " AND b.data_deposito >= ?"
        params.append(desde)
    params.append(limite)

    linhas = _linhas(
        f"""SELECT i.numero_inpi, any_value(i.simbolo) simbolo, any_value(c.titulo) titulo,
                   any_value(b.data_deposito) data_deposito
            FROM ipc i
            LEFT JOIN conteudo c USING (numero_inpi)
            LEFT JOIN biblio b USING (numero_inpi)
            WHERE i.simbolo LIKE ?{filtro}
            GROUP BY i.numero_inpi
            ORDER BY data_deposito DESC NULLS LAST
            LIMIT ?""",
        params,
    )
    return {"simbolo": simbolo, "retornados": len(linhas), "resultados": linhas}


@mcp.tool()
def inpi_despachos_por_rpi(numero_rpi: int | None = None, desde: str | None = None,
                           codigo: str | None = None, limite: int = 50) -> dict:
    """Despachos publicados numa RPI, ou a partir de uma data, opcionalmente por codigo.

    USE QUANDO: for varrer o que o INPI publicou numa semana -- vigilancia de
    concorrencia, ou conferir se saiu despacho de um codigo especifico.

    Args:
        numero_rpi: numero da revista (ex.: 2898).
        desde: 'AAAA-MM-DD'; use no lugar de numero_rpi para uma janela.
        codigo: codigo de despacho exato (ex.: '9.2' indeferimento, '7.1'
            sobrestamento apos parecer, '11.1' arquivamento).
        limite: 1 a 200.
    """
    limite = max(1, min(limite, 200))
    cond, params = [], []
    if numero_rpi is not None:
        cond.append("d.numero_rpi = ?")
        params.append(numero_rpi)
    if desde:
        cond.append("d.data_rpi >= ?")
        params.append(desde)
    if codigo:
        cond.append("d.codigo_despacho = ?")
        params.append(codigo)
    if not cond:
        return {"erro": True, "mensagem": "Informe numero_rpi, desde, ou ambos."}
    params.append(limite)

    linhas = _linhas(
        f"""SELECT d.numero_inpi, d.numero_rpi, d.data_rpi, d.codigo_despacho,
                   d.complemento_despacho, any_value(c.titulo) titulo
            FROM despachos d LEFT JOIN conteudo c USING (numero_inpi)
            WHERE {' AND '.join(cond)}
            GROUP BY ALL
            ORDER BY d.data_rpi DESC, d.numero_inpi
            LIMIT ?""",
        params,
    )
    for l in linhas:
        l["prazo_declarado_dias"] = _prazo_declarado(l.get("complemento_despacho"))
    return {"retornados": len(linhas), "resultados": linhas}


@mcp.tool()
def inpi_portfolio_titular(nome: str, limite: int = 50) -> dict:
    """Pedidos de um depositante. Inteligencia competitiva sobre o mercado brasileiro.

    Args:
        nome: parte do nome do depositante (case-insensitive).
    """
    limite = max(1, min(limite, 200))
    linhas = _linhas(
        """SELECT dp.numero_inpi, any_value(dp.depositante) depositante,
                  any_value(dp.pais) pais, any_value(c.titulo) titulo,
                  any_value(b.data_deposito) data_deposito
           FROM depositantes dp
           LEFT JOIN conteudo c USING (numero_inpi)
           LEFT JOIN biblio b USING (numero_inpi)
           WHERE dp.depositante ILIKE ?
           GROUP BY dp.numero_inpi
           ORDER BY data_deposito DESC NULLS LAST
           LIMIT ?""",
        [f"%{nome.strip()}%", limite],
    )
    return {"nome_buscado": nome, "retornados": len(linhas), "resultados": linhas}


@mcp.tool()
def inpi_cobertura() -> dict:
    """Ate quando a base local esta atualizada, e o que ela contem.

    USE QUANDO: for afirmar qualquer coisa sobre ausencia de anterioridade ou
    sobre andamento processual. Um resultado vazio de uma base desatualizada nao
    e evidencia de nada -- e preciso saber a data de corte antes de concluir.
    """
    r = _linhas(
        """SELECT min(data_rpi) primeira_rpi, max(data_rpi) ultima_rpi,
                  max(numero_rpi) ultimo_numero_rpi, count(*) despachos
           FROM despachos"""
    )[0]
    r["processos"] = _linhas("SELECT count(*) n FROM biblio")[0]["n"]
    r["com_titulo_resumo"] = _linhas("SELECT count(*) n FROM conteudo")[0]["n"]
    r["fonte"] = "https://dadosabertos.inpi.gov.br/index/patentes/ (CSV, diario)"
    r["nota"] = (
        "A base e um dump local. Para atualizar, rebaixe os CSVs e rode "
        "'python inpi/ingest.py'. Despachos posteriores a ultima_rpi nao estao aqui."
    )
    return r


if __name__ == "__main__":
    mcp.run()
