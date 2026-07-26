"""Servidor MCP sobre a base de dados abertos de patentes do INPI (local, DuckDB).

Por que existe: PPUBS so ve os EUA; o EPO OPS cobre BR pelo INPADOC mas nao tem
texto integral brasileiro nem o historico completo de despachos. Esta camada da
busca em texto de patente BR e o acompanhamento processual, offline e sem
depender da rede do INPI -- que, alias, esta inalcancavel desta maquina
(revistas.inpi.gov.br derruba o handshake TLS; ver inpi/referencias/fontes-rpi.md).

Fonte: https://dadosabertos.inpi.gov.br/index/patentes/ (CSV, atualizado diariamente).
Carregue com:  python inpi/ingest.py

SOBRE PRAZOS -- leia antes de mexer. Ha dois casos, e eles sao diferentes:

1. PRAZO DE EXIGENCIA: NAO calculamos. Sao 432 codigos de despacho, nenhum
   consistente, e so 0,83% dos despachos declaram os dias no texto. Calcular por
   analogia entre codigos e exatamente como se perde direito de terceiro. O
   servidor devolve codigo, data da RPI e texto literal; quem conta e o procurador.

2. ANUIDADE: projetamos, porque depende de UMA data (o deposito) e de UMA regra
   legal fixa (art. 84). Deterministico e auditavel. Calibrado contra 285.409
   despachos reais. Ainda assim e PROJECAO, nao a conta do INPI -- ver anuidades.py.
"""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
from mcp.server.fastmcp import FastMCP

RAIZ_MOD = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ_MOD))
import anuidades as anu
import escritorios as esc
import jurisdicoes as jur

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

# Despacho de arquivamento/extincao cita o prazo que JA FOI PERDIDO. Exemplo real
# do codigo 11.2: "Arquivo o pedido ... em face da nao apresentacao de cumprimento
# da exigencia notificada na RPI 2596 ... em ate 90 (noventa) dias". Ler esses 90
# dias como prazo ativo diria ao operador que ha tres meses para agir sobre um
# pedido que ja morreu. Diante deste marcador, nao extraimos nada.
# Casa o VERBO DA DECISAO ja tomada, nao o aviso condicional. O proprio texto do
# despacho 2.5 -- que tem prazo ativo legitimo de 30 dias -- avisa que "o pedido com
# exigencia nao cumprida ... nao sera aceito"; isso e advertencia, nao arquivamento.
_RE_CONSUMADO = re.compile(
    r"\b(arquiv(?:o|a|ada|ado|amos|ei)|indefir(?:o|imos)|indeferid[oa]|"
    r"extint[oa]|em face d[ao] n[ãa]o)\b",
    re.I,
)

# "Anulada a publicacao codigo 21.6 na RPI n 2897 de 14/07/2026". Um despacho pode ser
# desfeito dias depois -- aconteceu no PI0803071 da Petrobras, onde a extincao por
# anuidade foi anulada sete dias apos. Quem le so o primeiro age sobre ato que deixou
# de existir.
# A palavra "codigo" e "do despacho" sao opcionais: 4,4% das anulacoes usam variantes
# como "Anulada a publicacao 6.7 na RPI 2068" ou "Anulada a publicacao do despacho 15.7".
_RE_ANULA = re.compile(
    r"anulad[ao]\s+a\s+publica[çc][ãa]o\s+(?:d[oe]\s+despacho\s+|c[óo]d(?:igo|\.)?\s*)?"
    r"(\d+(?:\.\d+)*)\s*,?\s*(?:,?\s*publicad[oa])?\s*na\s+RPI\s*n?[º°.]?\s*(\d+)",
    re.I,
)

# "Referente a 18a anuidade" / "Referente as 10a, 11a e 12a anuidades".
# ANCORADO na palavra 'anuidade': sem isso o regex varre o texto inteiro e captura
# "artigo 10o da resolucao 124/06" (~1.003 casos) e "25a Vara Federal" (12 processos,
# entre eles o PI0722029 da Carrier, cuja projecao saia vazia por isso).
_RE_BLOCO_ANUIDADE = re.compile(
    r"((?:\d{1,2}\s*[ªaº°][\s,.]*(?:e\s+a?\s*)?)+)anuidade", re.I
)
_RE_ORDINAL = re.compile(r"(\d{1,2})\s*[ªaº°]")


def _anuidades_citadas(texto: str | None) -> list[int]:
    """Numeros de anuidade citados, so os que precedem a palavra 'anuidade'."""
    t = texto or ""
    if "anuidade" not in t.lower():
        return []
    achados: set[int] = set()
    for bloco in _RE_BLOCO_ANUIDADE.findall(t):
        achados.update(
            int(n) for n in _RE_ORDINAL.findall(bloco) if 1 <= int(n) <= 25
        )
    return sorted(achados)


def _marca_anulacoes(despachos: list[dict]) -> None:
    """Marca in-place quais despachos foram anulados por um posterior."""
    anulados: dict[tuple[str, int], str] = {}
    for d in despachos:
        m = _RE_ANULA.search(d.get("complemento_despacho") or "")
        if m:
            anulados[(m.group(1), int(m.group(2)))] = str(d.get("data_rpi"))
    for d in despachos:
        chave = (str(d.get("codigo_despacho")), int(d.get("numero_rpi") or 0))
        d["anulado_em"] = anulados.get(chave)


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
    """Le "N (por extenso) dias" do texto do despacho. NAO e calculo de prazo.

    Isto e leitura mecanica de texto juridico livre, e a cobertura e de 0,83% dos
    5,3 milhoes de despachos. Por isso o campo se chama 'dias_citados_no_texto' na
    saida, e nao 'prazo': o numero pode se referir a um prazo ja perdido, ao prazo
    de outro ato, ou a uma advertencia condicional. O texto literal vai junto
    justamente para o humano decidir o que aquele numero significa.

    Conservador de proposito: na duvida devolve None, que manda ler o texto --
    sempre seguro. Um numero errado aqui perde direito de terceiro.
    """
    t = texto or ""
    achados = _RE_PRAZO.findall(t)
    if len(achados) != 1:
        return None  # zero: nao declarou. mais de um: ambiguo, qual deles vale?
    if _RE_CONSUMADO.search(t):
        return None  # o prazo citado e o que ja passou, nao um prazo a correr
    return int(achados[0])


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
        d["dias_citados_no_texto"] = _prazo_declarado(d.get("complemento_despacho"))
    _marca_anulacoes(despachos)

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
            "Este servidor NAO calcula prazo. 'dias_citados_no_texto' e leitura "
            "mecanica do texto do despacho e cobre 0,83% deles; quando vem null "
            "significa 'o texto nao trouxe um numero inequivoco', nunca 'nao ha "
            "prazo'. Mesmo preenchido, o numero pode se referir a prazo ja perdido "
            "ou ao prazo de outro ato -- por isso leia sempre "
            "'complemento_despacho'. Ao relatar, cite codigo, numero e data da RPI "
            "e o texto literal. A contagem e do procurador responsavel."
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
        l["dias_citados_no_texto"] = _prazo_declarado(l.get("complemento_despacho"))
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


# ---------------------------------------------------------------------------
# Anuidades: projecao (a unica projecao de prazo que este servidor faz)
# ---------------------------------------------------------------------------


def _estado_de(num: str, desp: list[dict], data_deposito) -> dict:
    """Deriva o estado de UM processo a partir dos despachos ja carregados.

    Nao consulta o banco -- por isso serve igual para um caso e para uma carteira
    inteira. Ver `_carregar_lote`, que faz a leitura em duas queries.
    """
    _marca_anulacoes(desp)
    vivos = [d for d in desp if not d.get("anulado_em")]

    em_aberto: set[int] = set()
    complementacao: set[int] = set()
    for d in vivos:
        cod = str(d.get("codigo_despacho"))
        citadas = _anuidades_citadas(d.get("complemento_despacho"))
        if cod in anu.CODIGOS_DEBITO_ANUIDADE:
            em_aberto.update(citadas)
        elif cod in anu.CODIGOS_COMPLEMENTACAO:
            complementacao.update(citadas)

    # Terminal so vale se nada o reverteu depois. Indeferimento cai por recurso
    # (codigo 100), arquivamento por restauracao. O PI0803071 foi indeferido em 2019,
    # teve recurso provido em 2023 e recebeu anuidade em 2026 -- tratar como encerrado
    # responderia "nao ha anuidade a pagar" sobre patente concedida e viva.
    terminal = None
    for d in vivos:
        cod = str(d.get("codigo_despacho"))
        if cod in anu.CODIGOS_TERMINAIS:
            terminal = d
        elif terminal and cod in anu.CODIGOS_REVERSAO:
            terminal = None

    return {
        "numero_inpi": num,
        "data_deposito": data_deposito,
        "anuidades_em_aberto": sorted(em_aberto),
        "anuidades_complementacao": sorted(complementacao),
        "encerrado_em": terminal["data_rpi"] if terminal else None,
        "despacho_terminal": terminal,
        "despachos": desp,
    }


def _carregar_lote(
    numeros: list[str] | None = None,
    titular: str | None = None,
    procurador: str | None = None,
    desde: str | None = None,
) -> tuple[dict[str, dict], int]:
    """Carrega despachos e deposito de uma carteira inteira em DUAS queries.

    O laço anterior fazia 2 queries por caso: 37,3 s para os 1.864 processos da
    Petrobras. Com semi-join sao 0,35 s -- fator 100x. Passar 1.864 placeholders num
    IN(...) tambem funciona mas custa 9 s; o JOIN contra a subquery e o caminho.

    Returns:
        (estados por numero, total de casos que o criterio casou antes de qualquer corte)
    """
    if numeros:
        alvo_sql = "SELECT unnest(?::VARCHAR[]) AS numero_inpi"
        params: list = [numeros]
    elif titular:
        alvo_sql = "SELECT DISTINCT numero_inpi FROM depositantes WHERE depositante ILIKE ?"
        params = [f"%{titular.strip()}%"]
    elif procurador:
        alvo_sql = "SELECT DISTINCT numero_inpi FROM procuradores WHERE procurador ILIKE ?"
        params = [f"%{procurador.strip()}%"]
    else:
        raise ValueError("Informe numeros, titular ou procurador.")

    total = con().execute(f"SELECT count(*) FROM ({alvo_sql}) t", params).fetchone()[0]

    filtro_data = " AND d.data_rpi >= ?" if desde else ""
    p_desp = params + ([desde] if desde else [])
    desp = _linhas(
        f"""WITH alvo AS ({alvo_sql})
            SELECT d.numero_inpi, d.numero_rpi, d.data_rpi, d.codigo_despacho,
                   d.complemento_despacho
            FROM despachos d JOIN alvo USING (numero_inpi)
            WHERE 1=1{filtro_data}
            ORDER BY d.numero_inpi, d.data_rpi""",
        p_desp,
    )
    deps = {
        r["numero_inpi"]: r["dep"]
        for r in _linhas(
            f"""WITH alvo AS ({alvo_sql})
                SELECT b.numero_inpi, min(b.data_deposito) dep
                FROM biblio b JOIN alvo USING (numero_inpi)
                WHERE b.data_deposito IS NOT NULL GROUP BY 1""",
            params,
        )
    }

    por_num: dict[str, list[dict]] = {}
    for d in desp:
        por_num.setdefault(d["numero_inpi"], []).append(d)

    chaves = set(por_num) | set(deps)
    return (
        {n: _estado_de(n, por_num.get(n, []), deps.get(n)) for n in chaves},
        total,
    )


@mcp.tool()
def inpi_anuidades(numero: str, hoje: str | None = None, quantas: int = 3) -> dict:
    """PROJETA as proximas anuidades de um pedido brasileiro (art. 84 da LPI).

    USE QUANDO: perguntarem "quando vence a proxima anuidade" de um caso.

    Isto e CALCULO, nao consulta -- o INPI nao publica vencimento futuro, publica
    consequencia. A projecao parte da data de deposito e da regra do art. 84,
    calibrada contra 285.409 despachos reais. Sempre confira na GRU e no controle
    de prazos do escritorio: pagamento em dia NAO gera despacho, entao a base nao
    sabe o que ja foi pago -- so o que foi notificado.

    Args:
        numero: em qualquer formato ('BR 10 2022 010731 2', 'PI0803071', ...).
        hoje: 'AAAA-MM-DD' como referencia. Informe sempre que quiser resultado
            reproduzivel; sem isso usa a data corrente do sistema.
        quantas: quantas janelas futuras devolver (1 a 10).
    """
    num = normaliza_numero(numero)
    ref = date.fromisoformat(hoje) if hoje else date.today()
    estados, _ = _carregar_lote(numeros=[num])
    est = estados.get(num)
    if not est or not est["data_deposito"]:
        return {
            "erro": True,
            "numero_inpi": num,
            "mensagem": (
                "Sem data de deposito na base -- nao ha data-base e portanto nao ha "
                "projecao possivel. Confira o numero."
            ),
        }

    r = anu.projetar(
        data_deposito=est["data_deposito"],
        numero_inpi=num,
        hoje=ref,
        em_aberto=est["anuidades_em_aberto"],
        complementacao=est["anuidades_complementacao"],
        encerrado_em=est["encerrado_em"],
        quantas_futuras=max(1, min(quantas, 10)),
    )
    r["numero_inpi"] = num
    r["referencia"] = ref.isoformat()
    if est["despacho_terminal"]:
        t = est["despacho_terminal"]
        r["despacho_terminal"] = {
            "codigo": t["codigo_despacho"],
            "data_rpi": str(t["data_rpi"]),
            "texto": t["complemento_despacho"],
        }
    # O 16.1 traz a vigencia publicada pelo INPI -- fonte melhor que o calculo do art. 40.
    v = [d for d in est["despachos"] if str(d.get("codigo_despacho")) == "16.1"
         and not d.get("anulado_em")]
    if v:
        r["vigencia_publicada_16_1"] = v[-1]["complemento_despacho"]
        r["nota_vigencia"] = (
            "O despacho 16.1 publica a vigencia; prefira-o ao 'fim_vigencia_calculado'."
        )
    return r


# Prazo de recurso: art. 212 da LPI, 60 dias da publicacao. Os codigos 100/121, que
# sao os despachos DE recurso, declaram 60 dias em 87-99% das ocorrencias -- uma das
# poucas constantes confiaveis da tabela de despachos.
DIAS_RECURSO = 60
# Art. 33: requerimento de exame em 36 meses do deposito. Nao requerido, o pedido e
# arquivado -- gera o despacho 11.1, o 11o codigo mais frequente da base (156.260).
MESES_EXAME = 36
# Despachos que evidenciam que o exame ja foi requerido ou que o pedido ja passou dele.
CODIGOS_EXAME_REQUERIDO = {
    "6.1", "6.6", "6.6.1", "6.7", "6.20", "6.21", "6.23", "7.1",
    "9.1", "9.2", "16.1", "11.2",
}
CODIGOS_EXIGENCIA = {"2.5", "6.1", "6.6", "6.7", "6.20", "6.21", "7.1"}


def _prazos_de(est: dict, hoje: date, tipos: set[str], quantas: int = 4) -> list[dict]:
    """Todos os prazos projetaveis de um processo. Nao consulta o banco."""
    num, dep = est["numero_inpi"], est["data_deposito"]
    if not dep:
        return []
    saida: list[dict] = []
    vivos = [d for d in est["despachos"] if not d.get("anulado_em")]
    encerrado = est["encerrado_em"] is not None

    if "anuidade" in tipos and not encerrado:
        p = anu.projetar(dep, num, hoje, em_aberto=est["anuidades_em_aberto"],
                         complementacao=est["anuidades_complementacao"],
                         quantas_futuras=quantas)
        for j in p.get("anuidades", []):
            saida.append({
                "tipo": "anuidade", "numero_inpi": num,
                "descricao": f"{j['anuidade']}a anuidade",
                "prazo": j["fim_complementar"], "status": j["status"],
                "inicio": j["inicio_ordinario"], "fim_ordinario": j["fim_ordinario"],
                "base_legal": "LPI art. 84",
                **({"alerta": j["alerta"]} if "alerta" in j else {}),
                **({"nota": j["nota"]} if "nota" in j else {}),
            })

    if "exame" in tipos and not encerrado:
        ja = any(str(d["codigo_despacho"]) in CODIGOS_EXAME_REQUERIDO for d in vivos)
        if not ja:
            limite = anu._mais_meses(dep, MESES_EXAME)
            if limite >= hoje:
                saida.append({
                    "tipo": "exame", "numero_inpi": num,
                    "descricao": "Requerimento de exame (art. 33)",
                    "prazo": limite.isoformat(),
                    "status": "em_aberto",
                    "base_legal": "LPI art. 33 - 36 meses do deposito",
                    "alerta": "FATAL: nao requerido, o pedido e arquivado (despacho 11.1).",
                    "nota": ("Nenhum despacho de exame foi localizado. Peticao protocolada "
                             "e ainda nao publicada NAO aparece na base -- confira."),
                })

    if "recurso" in tipos:
        for d in vivos:
            if str(d["codigo_despacho"]) not in ("9.2", "11.1", "11.2", "11.5"):
                continue
            limite = d["data_rpi"] + timedelta(days=DIAS_RECURSO)
            if limite >= hoje:
                saida.append({
                    "tipo": "recurso", "numero_inpi": num,
                    "descricao": f"Recurso do despacho {d['codigo_despacho']}",
                    "prazo": limite.isoformat(),
                    "status": "em_aberto",
                    "publicado_em": str(d["data_rpi"]), "rpi": d["numero_rpi"],
                    "base_legal": f"LPI art. 212 - {DIAS_RECURSO} dias da publicacao",
                    "texto_despacho": d["complemento_despacho"],
                })

    if "vigencia" in tipos and not encerrado:
        fim = anu.fim_vigencia(dep, num)
        if fim >= hoje:
            v = [d for d in vivos if str(d["codigo_despacho"]) == "16.1"]
            saida.append({
                "tipo": "vigencia", "numero_inpi": num,
                "descricao": f"Fim de vigencia ({anu.natureza(num)})",
                "prazo": fim.isoformat(), "status": "calculado",
                "base_legal": "LPI art. 40",
                **({"vigencia_publicada_16_1": v[-1]["complemento_despacho"],
                    "nota": "O 16.1 publica a vigencia; prefira-o ao calculo."} if v else {}),
            })

    if "exigencia" in tipos and not encerrado:
        for d in vivos:
            if str(d["codigo_despacho"]) not in CODIGOS_EXIGENCIA:
                continue
            posteriores = [x for x in vivos if x["data_rpi"] > d["data_rpi"]]
            if posteriores:
                continue  # houve movimentacao depois; provavelmente respondida
            saida.append({
                "tipo": "exigencia", "numero_inpi": num,
                "descricao": f"Exigencia {d['codigo_despacho']} sem movimentacao posterior",
                "prazo": None, "status": "conferir_se_respondida",
                "publicado_em": str(d["data_rpi"]), "rpi": d["numero_rpi"],
                "dias_citados_no_texto": _prazo_declarado(d["complemento_despacho"]),
                "texto_despacho": d["complemento_despacho"],
                "nota": ("NAO afirma que esta sem resposta: peticao protocolada e ainda nao "
                         "publicada nao aparece na base. E lista de conferencia."),
            })

    return saida


@mcp.tool()
def inpi_prazos_carteira(
    titular: str | None = None,
    procurador: str | None = None,
    numeros: list[str] | None = None,
    de: str | None = None,
    ate: str | None = None,
    tipos: list[str] | None = None,
    limite_resultados: int = 500,
) -> dict:
    """PROJETA os prazos de uma carteira inteira numa janela de datas.

    USE QUANDO: perguntarem "quantas anuidades a Petrobras paga em julho de 2026",
    "o que vence na nossa carteira no proximo trimestre", "quais casos vencem o prazo
    de exame".

    Filtre por 'procurador' (a carteira do escritorio), 'titular' (o cliente) ou
    'numeros'. A janela 'de'/'ate' filtra pela data do prazo.

    Tipos disponiveis (padrao: todos menos 'exigencia'):
      anuidade  - art. 84, projetada da data de deposito
      exame     - art. 33, 36 meses do deposito. FATAL.
      recurso   - art. 212, 60 dias de indeferimento ou arquivamento
      vigencia  - art. 40, 20 anos (invencao) ou 15 (modelo de utilidade)
      exigencia - exigencias sem movimentacao posterior (lista de CONFERENCIA)

    ATENCAO: e PROJECAO, nao fatura. A base registra consequencia, nao vencimento
    futuro; pagamento em dia nao gera despacho. Use como lista de conferencia contra
    o controle de prazos do escritorio, nunca como substituto dele.
    """
    if not (titular or procurador or numeros):
        return {"erro": True, "mensagem": "Informe 'titular', 'procurador' ou 'numeros'."}
    try:
        d_ini = date.fromisoformat(de) if de else date.today()
        d_fim = date.fromisoformat(ate) if ate else anu._mais_meses(d_ini, 12)
    except ValueError as e:
        return {"erro": True, "mensagem": f"Data invalida (use AAAA-MM-DD): {e}"}

    escolhidos = set(tipos) if tipos else {"anuidade", "exame", "recurso", "vigencia"}
    validos = {"anuidade", "exame", "recurso", "vigencia", "exigencia"}
    if not escolhidos <= validos:
        return {"erro": True, "mensagem": f"tipos deve ser subconjunto de {sorted(validos)}"}

    alvos = [normaliza_numero(n) for n in numeros] if numeros else None
    estados, total = _carregar_lote(numeros=alvos, titular=titular, procurador=procurador)

    prazos, encerrados, sem_base = [], 0, 0
    for est in estados.values():
        if not est["data_deposito"]:
            sem_base += 1
            continue
        if est["encerrado_em"]:
            encerrados += 1
        for p in _prazos_de(est, d_ini, escolhidos):
            if p["prazo"] is None or d_ini.isoformat() <= p["prazo"] <= d_fim.isoformat():
                prazos.append(p)

    prazos.sort(key=lambda x: (x["prazo"] or "9999", x["numero_inpi"]))
    truncado = len(prazos) > limite_resultados
    por_tipo: dict[str, int] = {}
    for p in prazos:
        por_tipo[p["tipo"]] = por_tipo.get(p["tipo"], 0) + 1

    return {
        "criterio": {
            "titular": titular, "procurador": procurador,
            "casos_no_criterio": total, "casos_avaliados": len(estados),
            "de": d_ini.isoformat(), "ate": d_fim.isoformat(),
            "tipos": sorted(escolhidos),
        },
        "resumo": {
            "prazos_encontrados": len(prazos),
            "por_tipo": por_tipo,
            "casos_encerrados": encerrados,
            "casos_sem_data_de_deposito": sem_base,
        },
        "truncado": truncado,
        **({"aviso_truncamento":
            f"Exibindo {limite_resultados} de {len(prazos)} prazos. Aumente "
            "'limite_resultados' ou estreite a janela para ver o resto."} if truncado else {}),
        "prazos": prazos[:limite_resultados],
        "aviso": (
            "PROJECAO, nao fatura. Nenhum destes vencimentos foi publicado pelo INPI -- "
            "sao calculados a partir da data de deposito e das regras citadas em "
            "'base_legal'. A base nao sabe o que ja foi pago nem o que foi protocolado "
            "sem publicacao. Confira contra o controle de prazos do escritorio."
        ),
    }


@mcp.tool()
def inpi_regra_jurisdicao(jurisdicao: str) -> dict:
    """Regra de anuidade/manutencao e prazo de fase nacional de uma jurisdicao.

    USE QUANDO: for orientar sobre manutencao no exterior (US, EP, CN, JP, ...).

    So o Brasil devolve datas projetadas -- e a unica regra com evidencia nesta base
    (calibrada contra 285.409 despachos). As demais sao transcricao de legislacao,
    sem verificacao: devolvem a REGRA e a base legal para conversar com o associado
    local, e nao datas. Para liberar uma jurisdicao, preencha 'revisado_por' em
    inpi/referencias/anuidades-por-jurisdicao.csv.
    """
    return jur.descrever(jurisdicao)


@mcp.tool()
def inpi_prazo_fase_nacional(data_prioridade: str,
                             jurisdicoes: list[str] | None = None) -> dict:
    """Prazos de entrada em fase nacional do PCT, contados da prioridade mais antiga.

    USE QUANDO: houver um PCT e for preciso decidir onde entrar. Devolve as datas
    ordenadas, da mais proxima para a mais distante.

    Este marco (30 ou 31 meses) vem do proprio PCT e e uniforme, por isso projetamos
    mesmo sem revisao por jurisdicao. Ainda assim confirme com o associado: perder
    este prazo e irreversivel na maioria dos paises.

    Args:
        data_prioridade: 'AAAA-MM-DD' da prioridade mais antiga.
        jurisdicoes: siglas (ex.: ['US','EP','CN']). Omita para todas as da tabela.
    """
    return jur.fase_nacional(date.fromisoformat(data_prioridade), jurisdicoes)


# ---------------------------------------------------------------------------
# Vigilancia de carteira
# ---------------------------------------------------------------------------


@mcp.tool()
def inpi_novidades(desde: str, numeros: list[str] | None = None,
                   titular: str | None = None, procurador: str | None = None) -> dict:
    """O que saiu de novo numa carteira desde uma data.

    USE QUANDO: perguntarem "o que mudou nos nossos casos esta semana" -- e a
    pergunta operacional mais frequente de um escritorio.

    Filtre por 'procurador' (a carteira do escritorio), 'titular' (o cliente) ou
    'numeros'. Marca despachos ANULADOS por publicacao posterior: no PI0803071 da
    Petrobras, a extincao por anuidade (21.6, RPI 2897) foi anulada sete dias depois
    pelo 21.8. Quem lesse so o primeiro agiria sobre ato que deixou de existir.

    Args:
        desde: 'AAAA-MM-DD'. Use a data da ultima conferencia.
        numeros: processos especificos, em qualquer formato.
        titular: nome do depositante.
        procurador: nome do escritorio.
    """
    if not (numeros or titular or procurador):
        return {"erro": True, "mensagem": "Informe 'numeros', 'titular' ou 'procurador'."}
    try:
        d_desde = date.fromisoformat(desde)
    except ValueError:
        return {
            "erro": True,
            "mensagem": f"'desde' deve ser AAAA-MM-DD; recebido {desde!r}. "
                        "Formato errado devolveria zero novidades sem erro.",
        }

    alvos = [normaliza_numero(n) for n in numeros] if numeros else None
    # 'desde' entra no SQL. Seguro para _marca_anulacoes: a anulacao e sempre
    # posterior ao despacho que ela anula, entao a janela nunca corta o anulador
    # deixando o anulado.
    estados, total = _carregar_lote(
        numeros=alvos, titular=titular, procurador=procurador, desde=d_desde.isoformat()
    )

    novidades = []
    for est in estados.values():
        for d in est["despachos"]:
            d["dias_citados_no_texto"] = _prazo_declarado(d.get("complemento_despacho"))
            d["terminal"] = str(d["codigo_despacho"]) in anu.CODIGOS_TERMINAIS
            novidades.append(d)
    novidades.sort(key=lambda x: (str(x["data_rpi"]), x["numero_inpi"]))

    cob = _linhas("SELECT max(data_rpi) u, max(numero_rpi) n FROM despachos")[0]
    anulados = sum(1 for d in novidades if d.get("anulado_em"))
    return {
        "desde": d_desde.isoformat(),
        "criterio": {"titular": titular, "procurador": procurador,
                     "casos_no_criterio": total},
        "novidades": len(novidades),
        "despachos_anulados_no_periodo": anulados,
        "cobertura_da_base": {"ultima_rpi": str(cob["u"]), "numero": cob["n"]},
        "resultados": novidades,
        "aviso": (
            f"A base vai ate a RPI {cob['n']} de {cob['u']}. Nada posterior a isso "
            "aparece aqui -- reingira antes de concluir que nao houve movimentacao. "
            "Confira 'anulado_em': despacho anulado por publicacao posterior nao produz "
            "efeito, e so o despacho seguinte revela isso."
        ),
    }


# ---------------------------------------------------------------------------
# Carteira, mercado e prospeccao
# ---------------------------------------------------------------------------

_AVISO_PESSOAL = (
    "Esta lista contem PESSOA FISICA. O INPI ja publica o CPF mascarado, mas nome e "
    "endereco sao dado pessoal: uso comercial exige base legal propria (LGPD art. 7o). "
    "Ver docs/lgpd.md. Pessoa juridica nao tem essa restricao."
)


def _chave_escritorio(nome: str) -> str:
    """Resolve o nome digitado para a chave canonica de agrupamento."""
    return esc.normalizar(nome)


@mcp.tool()
def inpi_escritorio_resolver(nome: str) -> dict:
    """Mostra em que chave um nome de escritorio cai, e quais grafias ela agrupa.

    USE QUANDO: antes de confiar em qualquer numero de carteira ou de mercado. A base
    tem 17.521 grafias de procurador para ~10 mil escritorios reais -- a Clarke Modet
    sozinha aparece em 42 formas. Se a chave errada for usada, todo o resto erra junto.
    """
    chave = _chave_escritorio(nome)
    grafias = _linhas(
        """SELECT e.original, count(DISTINCT p.numero_inpi) n
           FROM escritorios e JOIN procuradores p ON p.procurador = e.original
           WHERE e.chave = ? GROUP BY 1 ORDER BY n DESC""",
        [chave],
    )
    parecidas = _linhas(
        """SELECT DISTINCT chave FROM escritorios
           WHERE chave ILIKE ? AND chave <> ? LIMIT 15""",
        [f"%{chave.split()[0]}%" if chave else "%", chave],
    )
    return {
        "nome_consultado": nome,
        "chave": chave,
        "processos": sum(g["n"] for g in grafias),
        "grafias_agrupadas": len(grafias),
        "grafias": grafias[:30],
        "chaves_parecidas_nao_agrupadas": [p["chave"] for p in parecidas],
        "nota": (
            "'chaves_parecidas_nao_agrupadas' sao candidatas a erro de digitacao que a "
            "normalizacao nao une (ex.: 'CLARK MODET'). Se alguma for a mesma empresa, "
            "acrescente em inpi/referencias/escritorios-apelidos.csv e reingira."
        ),
    }


@mcp.tool()
def inpi_carteira(escritorio: str, cliente: str | None = None,
                  apenas_vivos: bool = True, limite: int = 200) -> dict:
    """Carteira de um escritorio, opcionalmente filtrada por cliente.

    USE QUANDO: perguntarem "quantos casos temos", "quais casos do cliente X",
    "nossa carteira em determinada area".

    Agrupa as grafias do nome automaticamente. Confira com inpi_escritorio_resolver
    se o numero parecer estranho.
    """
    chave = _chave_escritorio(escritorio)
    params: list = [chave]
    filtro_cli = ""
    if cliente:
        filtro_cli = " AND dp.depositante ILIKE ?"
        params.append(f"%{cliente.strip()}%")

    linhas = _linhas(
        f"""WITH alvo AS (
              SELECT DISTINCT p.numero_inpi
              FROM procuradores p JOIN escritorios e ON e.original = p.procurador
              WHERE e.chave = ?
            )
            SELECT a.numero_inpi,
                   any_value(dp.depositante) titular,
                   any_value(c.titulo) titulo,
                   any_value(b.data_deposito) data_deposito,
                   max(d.data_rpi) ultimo_despacho,
                   count(DISTINCT d.codigo_despacho) n_despachos
            FROM alvo a
            LEFT JOIN depositantes dp USING (numero_inpi)
            LEFT JOIN conteudo c USING (numero_inpi)
            LEFT JOIN biblio b USING (numero_inpi)
            LEFT JOIN despachos d USING (numero_inpi)
            WHERE 1=1{filtro_cli}
            GROUP BY a.numero_inpi
            ORDER BY ultimo_despacho DESC NULLS LAST""",
        params,
    )

    if apenas_vivos:
        estados, _ = _carregar_lote(numeros=[l["numero_inpi"] for l in linhas][:5000])
        linhas = [
            l for l in linhas
            if not (estados.get(l["numero_inpi"], {}).get("encerrado_em"))
        ]

    return {
        "escritorio": escritorio,
        "chave": chave,
        "cliente": cliente,
        "apenas_vivos": apenas_vivos,
        "total": len(linhas),
        "truncado": len(linhas) > limite,
        "casos": linhas[:limite],
    }


@mcp.tool()
def inpi_mercado(ipc: str | None = None, desde: str | None = None,
                 top: int = 20) -> dict:
    """Ranking de escritorios por volume de processos. Inteligencia competitiva.

    USE QUANDO: perguntarem participacao de mercado, quem lidera uma area tecnica,
    ou como a nossa posicao evoluiu.

    Args:
        ipc: prefixo de classificacao (ex.: 'C08' para polimeros, 'A61K' para farma).
        desde: 'AAAA-MM-DD' sobre a data de deposito.
        top: quantos escritorios listar.
    """
    cond, params = [], []
    if ipc:
        cond.append("i.simbolo LIKE ?")
        params.append(f"{ipc.strip()}%")
    if desde:
        cond.append("b.data_deposito >= ?")
        params.append(desde)
    where = (" WHERE " + " AND ".join(cond)) if cond else ""
    params.append(max(1, min(top, 100)))

    linhas = _linhas(
        f"""SELECT e.chave escritorio, count(DISTINCT p.numero_inpi) processos
            FROM procuradores p
            JOIN escritorios e ON e.original = p.procurador
            LEFT JOIN ipc i USING (numero_inpi)
            LEFT JOIN biblio b USING (numero_inpi)
            {where}
            GROUP BY 1 ORDER BY processos DESC LIMIT ?""",
        params,
    )
    total = sum(l["processos"] for l in linhas)
    for l in linhas:
        l["participacao_no_top"] = round(l["processos"] / total * 100, 1) if total else 0
    return {
        "filtro": {"ipc": ipc, "desde": desde},
        "ranking": linhas,
        "nota": (
            "'participacao_no_top' e sobre a soma dos listados, nao sobre o mercado "
            "inteiro."
        ),
        "aviso_agente_pessoa_fisica": (
            "ATENCAO ao ler este ranking: quando o INPI registra o AGENTE pessoa fisica, "
            "ele o faz NO LUGAR da banca, nao junto. Medido: 'ORLANDO DE SOUZA' tem "
            "11.972 processos e apenas 4 em comum com 'CLARKE MODET'. Logo, bancas cujos "
            "agentes assinam em nome proprio aparecem subestimadas, e nomes de pessoa "
            "fisica aparecem no ranking como se fossem escritorios. Antes de citar "
            "participacao de mercado, verifique com inpi_escritorio_resolver quais nomes "
            "de agente pertencem a cada banca e acrescente-os a "
            "inpi/referencias/escritorios-apelidos.csv."
        ),
    }


@mcp.tool()
def inpi_prospeccao(excluir_escritorio: str, ipc: str | None = None,
                    uf: str | None = None, min_pedidos: int = 5,
                    desde: str | None = None, limite: int = 50) -> dict:
    """Titulares com carteira relevante que NAO sao representados por nos.

    USE QUANDO: for prospectar. Lista depositantes ativos, ordenados por volume,
    excluindo quem ja e cliente do escritorio informado.

    Args:
        excluir_escritorio: o nosso nome -- quem ja representamos sai da lista.
        ipc: prefixo de classificacao para focar numa area tecnica.
        uf: sigla do estado do depositante.
        min_pedidos: volume minimo para entrar na lista.
        desde: 'AAAA-MM-DD' sobre a data de deposito, para pegar quem esta ativo.
    """
    chave_nossa = _chave_escritorio(excluir_escritorio)
    cond, params = ["dp.depositante IS NOT NULL"], []
    if ipc:
        cond.append("i.simbolo LIKE ?")
        params.append(f"{ipc.strip()}%")
    if uf:
        cond.append("dp.estado = ?")
        params.append(uf.strip().upper())
    if desde:
        cond.append("b.data_deposito >= ?")
        params.append(desde)
    params += [chave_nossa, min_pedidos]

    # Agrupa pelo nome cru no SQL e normaliza depois, em Python, sobre as poucas
    # centenas de linhas do resultado -- materializar as ~500 mil chaves de titular
    # na carga nao termina em tempo util, e aqui o volume e trivial.
    brutos = _linhas(
        f"""SELECT dp.depositante titular,
                   any_value(dp.pais) pais, any_value(dp.estado) uf,
                   any_value(dp.tipopessoadepositante) tipo_pessoa,
                   count(DISTINCT dp.numero_inpi) pedidos,
                   max(b.data_deposito) deposito_mais_recente
            FROM depositantes dp
            LEFT JOIN ipc i USING (numero_inpi)
            LEFT JOIN biblio b USING (numero_inpi)
            WHERE {' AND '.join(cond)}
              AND dp.numero_inpi NOT IN (
                    SELECT p.numero_inpi FROM procuradores p
                    JOIN escritorios e ON e.original = p.procurador
                    WHERE e.chave = ?
              )
            GROUP BY dp.depositante
            HAVING count(DISTINCT dp.numero_inpi) >= ?
            ORDER BY pedidos DESC LIMIT 3000""",
        params,
    )

    agrupado: dict[str, dict] = {}
    for b in brutos:
        k = esc.normalizar(b["titular"])
        if k not in agrupado:
            agrupado[k] = {**b, "titular_chave": k, "grafias": 1}
        else:
            agrupado[k]["pedidos"] += b["pedidos"]
            agrupado[k]["grafias"] += 1
            if str(b["deposito_mais_recente"]) > str(agrupado[k]["deposito_mais_recente"]):
                agrupado[k]["deposito_mais_recente"] = b["deposito_mais_recente"]
    linhas = sorted(agrupado.values(), key=lambda x: -x["pedidos"])[: max(1, min(limite, 500))]

    tem_pf = any((l.get("tipo_pessoa") or "").lower().startswith("pessoa f") for l in linhas)
    r = {
        "excluido": {"escritorio": excluir_escritorio, "chave": chave_nossa},
        "filtro": {"ipc": ipc, "uf": uf, "min_pedidos": min_pedidos, "desde": desde},
        "encontrados": len(linhas),
        "titulares": linhas,
        "nota": (
            "Ausencia da nossa chave significa que nao ha registro de representacao "
            "NESTA base. O titular pode ser cliente por outra via (marcas, contratos) "
            "ou ter mudado de procurador sem publicacao. Confira antes de abordar."
        ),
    }
    if tem_pf:
        r["aviso_dado_pessoal"] = _AVISO_PESSOAL
    return r


# NAO EXISTE inpi_trocas_de_escritorio, e a ausencia e deliberada.
#
# O plano previa detectar perda e ganho de clientes por procuradores.
# data_inicio_procurador. Medido: apenas 262 processos em 775.370 tem mais de um
# escritorio distinto, e nesses poucos os dois registros trazem a MESMA data -- sao
# a banca e o agente pessoa fisica anotados juntos, nao uma troca ao longo do tempo.
# A tabela guarda a representacao vigente, nao a serie historica. Uma tool aqui
# devolveria sempre zero, o que e pior que nao existir: passa a impressao de que
# nenhum cliente saiu.


if __name__ == "__main__":
    mcp.run()
