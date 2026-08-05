"""Consulta processual: ficha de processo, busca por texto/IPC, despachos, titulares.

Extraido de inpi_mcp.py na modularizacao da Fase 0. Logica e docstrings de tool
inalteradas -- so mudou o arquivo que as contem.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from inpi.db import con
from inpi.mcp_app import mcp


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
def inpi_titular_resolver(nome: str) -> dict:
    """Mostra em que chave canonica um titular cai, e quais grafias ela agrupa.

    USE QUANDO: antes de citar qualquer numero por titular. Sao 362.483 grafias de
    depositante na base -- so a Petrobras aparece em 66 formas, com 8 documentos
    diferentes entre matriz, filiais e registros sem CNPJ.

    A chave e 'CNPJ:xxxxxxxx' (raiz de 8 digitos, que junta matriz e filial) quando ha
    documento, e o nome normalizado quando nao ha -- caso de 65% dos depositantes, que
    sao estrangeiros.
    """
    chaves = _linhas(
        """SELECT t.chave, count(DISTINCT dp.depositante) grafias,
                  count(DISTINCT dp.numero_inpi) processos,
                  arg_max(dp.depositante, 1) exemplo, any_value(t.tem_cnpj) tem_cnpj
           FROM depositantes dp JOIN titulares t ON t.original = dp.depositante
           WHERE dp.depositante ILIKE ?
           GROUP BY t.chave ORDER BY processos DESC LIMIT 12""",
        [f"%{nome.strip()}%"],
    )
    principal = chaves[0]["chave"] if chaves else None
    grafias = _linhas(
        """SELECT dp.depositante, count(DISTINCT dp.numero_inpi) n
           FROM depositantes dp JOIN titulares t ON t.original = dp.depositante
           WHERE t.chave = ? GROUP BY 1 ORDER BY n DESC LIMIT 20""",
        [principal],
    ) if principal else []

    return {
        "nome_consultado": nome,
        "chave_principal": principal,
        "chaves_encontradas": chaves,
        "grafias_da_principal": grafias,
        "nota": (
            "Varias chaves para o mesmo grupo economico e esperado: subsidiarias tem "
            "CNPJ proprio (Petrobras, Transpetro e Petrobras Distribuidora sao raizes "
            "distintas). Some-as se a pergunta for sobre o grupo."
        ),
    }


@mcp.tool()
def inpi_portfolio_titular(nome: str, agrupar: bool = True, limite: int = 50) -> dict:
    """Pedidos de um depositante. Inteligencia competitiva sobre o mercado brasileiro.

    Args:
        nome: parte do nome do depositante (case-insensitive).
        agrupar: True junta todas as grafias do mesmo titular pela chave canonica --
            a Petrobras tem 66 grafias e 8 documentos. False busca so pelo texto.
    """
    limite = max(1, min(limite, 200))
    if agrupar:
        linhas = _linhas(
            """WITH alvo AS (
                 SELECT DISTINCT t.chave FROM depositantes dp
                 JOIN titulares t ON t.original = dp.depositante
                 WHERE dp.depositante ILIKE ?
               )
               SELECT dp.numero_inpi, any_value(dp.depositante) depositante,
                      any_value(t.chave) titular_chave,
                      any_value(dp.pais) pais, any_value(c.titulo) titulo,
                      any_value(b.data_deposito) data_deposito
               FROM depositantes dp
               JOIN titulares t ON t.original = dp.depositante
               JOIN alvo a ON a.chave = t.chave
               LEFT JOIN conteudo c USING (numero_inpi)
               LEFT JOIN biblio b USING (numero_inpi)
               GROUP BY dp.numero_inpi
               ORDER BY data_deposito DESC NULLS LAST LIMIT ?""",
            [f"%{nome.strip()}%", limite],
        )
    else:
        linhas = _linhas(
            """SELECT dp.numero_inpi, any_value(dp.depositante) depositante,
                      any_value(dp.pais) pais, any_value(c.titulo) titulo,
                      any_value(b.data_deposito) data_deposito
               FROM depositantes dp
               LEFT JOIN conteudo c USING (numero_inpi)
               LEFT JOIN biblio b USING (numero_inpi)
               WHERE dp.depositante ILIKE ?
               GROUP BY dp.numero_inpi
               ORDER BY data_deposito DESC NULLS LAST LIMIT ?""",
            [f"%{nome.strip()}%", limite],
        )
    return {"nome_buscado": nome, "agrupado": agrupar,
            "retornados": len(linhas), "resultados": linhas}


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
        "A base e um dump local. Para atualizar: 'python inpi/ingest.py --baixar'. "
        "Despachos posteriores a ultima_rpi nao estao aqui."
    )

    # A base envelhece em silencio, e base velha faz busca vazia parecer ausencia de
    # anterioridade. Uma RPI sai por semana, entao mais de 8 dias significa que ja
    # houve publicacao que este dump nao viu.
    atraso = (date.today() - r["ultima_rpi"]).days
    r["dias_desde_a_ultima_rpi_carregada"] = atraso
    if atraso > 8:
        r["ALERTA_BASE_DESATUALIZADA"] = (
            f"A ultima RPI carregada tem {atraso} dias. O INPI publica semanalmente, "
            "as tercas -- ha pelo menos uma revista que esta base nao viu. NAO conclua "
            "ausencia de anterioridade nem de movimentacao processual antes de rodar "
            "'python inpi/ingest.py --baixar'."
        )
    return r
