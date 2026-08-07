"""A carteira de um cliente como entidade -- e nao como CSV chumbado no codigo.

Existe porque nenhuma fonte sozinha ve a carteira inteira:

  - a base do INPI ve o Brasil, e so quem assina em nome proprio;
  - a familia INPADOC ve o exterior, MENOS os paises do Acordo de Londres, onde a
    validacao de uma patente europeia nao gera publicacao nacional (46 dos 59 casos
    reais da Tecnored sao invisiveis assim);
  - a lista do escritorio ve tudo, mas so existe quando alguem a manda.

Por isso as tres fontes convivem na MESMA tabela, cada linha carimbada com a sua
origem. Quando discordam, a discordancia aparece -- nao e resolvida por sobrescrita
da ultima carga. Decidir qual data vale e do procurador.

BANCO SEPARADO, de proposito: ingest.py recria inpi.duckdb do zero a cada carga
(DROP e CREATE). Uma tabela de carteira la dentro seria destruida na proxima
ingestao dos dados abertos, em silencio, e ninguem descobriria ate faltar prazo.
"""

from __future__ import annotations

import csv
import io
import os
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent

BANCO = RAIZ / "data" / "carteira.duckdb"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS casos (
    cliente          VARCHAR NOT NULL,
    jurisdicao       VARCHAR NOT NULL,
    numero_norm      VARCHAR NOT NULL,
    fonte            VARCHAR NOT NULL,
    numero_oficial   VARCHAR,
    familia          VARCHAR,
    tipo             VARCHAR,
    data_prioridade  DATE,
    data_deposito    DATE,
    data_base        DATE,
    data_concessao   DATE,
    numero_pct       VARCHAR,
    equivalente_br   VARCHAR,
    status           VARCHAR,
    confianca        VARCHAR,
    visto_em         DATE,
    nota             VARCHAR,
    PRIMARY KEY (cliente, jurisdicao, numero_norm, fonte)
)
"""

# 'fonte' entra na chave primaria de proposito: e o que permite o mesmo caso existir
# tres vezes, uma por origem, com datas diferentes. Sem isso a ultima carga apagaria
# a divergencia -- que e exatamente o dado que o procurador precisa ver.

FONTES = {"lista", "inpi", "inpadoc", "inpadoc-legal", "epo-register"}


def conectar_carteira(banco: Path = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Conexao ao banco de carteira: MotherDuck (MOTHERDUCK_TOKEN no
    ambiente -- Fase 6, servidor remoto sem arquivo local) ou o arquivo local
    passado em 'banco'. Compartilhada por carteira.py, tarefas.py, radar.py e
    landscape/carteira_bridge.py -- todos vivem na mesma base logica.

    'banco' recebe o CAMINHO, nao um default fixo aqui: cada chamador passa
    a sua propria variavel BANCO/BANCO_TAREFAS/BANCO_CARTEIRA de modulo, para
    que testes que monkeypatcham essa variavel continuem valendo mesmo com a
    conexao centralizada aqui."""
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if token:
        c = duckdb.connect(f"md:?motherduck_token={token}")
        c.execute("CREATE DATABASE IF NOT EXISTS carteira")
        c.execute("USE carteira")
        return c
    banco = banco if banco is not None else BANCO
    banco.parent.mkdir(parents=True, exist_ok=True)
    if read_only and not banco.exists():
        raise RuntimeError(
            f"Nenhuma carteira ingerida ainda ({banco} nao existe). "
            "Use carteira_ingerir com a lista do escritorio, ou carteira_descobrir "
            "para levantar o que a base do INPI conhece."
        )
    return duckdb.connect(str(banco), read_only=read_only)


def con(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    c = conectar_carteira(BANCO, read_only)
    if not read_only:
        c.execute(ESQUEMA)
    return c


# --------------------------------------------------------------------------- #
# normalizacao
# --------------------------------------------------------------------------- #

def _sem_acento(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(ch) != "Mn"
    )


def normalizar_numero(jurisdicao: str, bruto: str) -> str:
    """Chave de comparacao de um numero oficial dentro de uma jurisdicao.

    O Brasil tem regra propria e ja resolvida (digito verificador, prefixo 'BR',
    kind code do EPO) -- reusa a do inpi_mcp. Para as demais, a normalizacao e
    deliberadamente grosseira: tira pontuacao, o prefixo de pais e o kind code.
    Ela serve para CASAR o mesmo caso vindo de duas fontes, nao para validar
    numero -- o numero que o operador le continua sendo 'numero_oficial'.
    """
    j = (jurisdicao or "").strip().upper()
    s = re.sub(r"[\s.\-/,]", "", (bruto or "").upper())
    if j == "BR":
        from inpi import inpi_mcp
        return inpi_mcp.normaliza_numero(bruto)
    if j and s.startswith(j):
        s = s[len(j):]
    # kind code no fim ('A1', 'B2', 'T3'), so quando ha digito antes
    s = re.sub(r"(?<=\d)[A-Z]\d?$", "", s)
    return s


def _data(v) -> date | None:
    """Aceita o que as fontes reais entregam, e nada mais.

    Devolver None e sempre seguro: vira 'sem data-base' na secao de lacunas. Chutar
    o formato nao e -- '03/04/2026' lido como mes/dia erra a anuidade em um mes.
    """
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10] if "-" in s or "/" in s else s, fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# leitura de arquivo ou texto colado
# --------------------------------------------------------------------------- #

SINONIMOS = {
    "jurisdicao": ("pais", "country", "jurisdicao", "jurisdiction", "estado", "territorio"),
    "numero_oficial": ("numerooficial", "numero", "number", "application", "applicationnumber",
                       "appno", "serial", "patente", "patent", "pedido", "processo",
                       "publicacao", "publication"),
    "familia": ("familia", "family", "caso", "case", "ref", "referencia", "nossoref"),
    "tipo": ("tipo", "type", "kind", "natureza"),
    "data_base": ("database", "databasedaanuidade"),
    "data_deposito": ("datadeposito", "deposito", "filing", "filingdate", "datadodeposito"),
    "data_concessao": ("dataconcessao", "concessao", "grant", "grantdate", "dataconcedida"),
    "data_prioridade": ("dataprioridade", "prioridade", "priority", "prioritydate"),
    "numero_pct": ("numeropct", "pct", "wo", "numerowo"),
    "status": ("status", "situacao", "estadodocaso"),
    "nota": ("nota", "obs", "observacao", "note", "comment", "comentario"),
}

_CAMPO_POR_SINONIMO = {s: campo for campo, ss in SINONIMOS.items() for s in ss}


def _chave_coluna(rotulo: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _sem_acento(str(rotulo or "")).lower())


def _mapear(cabecalho: list, mapa: dict | None) -> tuple[dict, list]:
    """(indice da coluna -> campo, rotulos nao reconhecidos)."""
    mapa = {_chave_coluna(k): v for k, v in (mapa or {}).items()}
    achados, ignorados = {}, []
    for i, rot in enumerate(cabecalho):
        k = _chave_coluna(rot)
        campo = mapa.get(k) or _CAMPO_POR_SINONIMO.get(k)
        if campo:
            achados[i] = campo
        elif str(rot or "").strip():
            ignorados.append(str(rot))
    return achados, ignorados


# 'BE EP1234567', 'BR 10 2022 010731 2', 'US-10,123,456-B2'
_RE_LINHA = re.compile(r"^\s*([A-Za-z]{2})\b[\s:;,|/-]*(.+?)\s*$")


def _linhas_de_texto(texto: str) -> tuple[list[dict], list[str]]:
    """Lista colada no chat. Uma linha, um caso: sigla do pais + numero."""
    casos, recusadas = [], []
    for ln in texto.splitlines():
        if not ln.strip() or _chave_coluna(ln).startswith("pais"):
            continue
        m = _RE_LINHA.match(ln)
        if not m or not re.search(r"\d", m.group(2)):
            recusadas.append(ln.strip())
            continue
        casos.append({"jurisdicao": m.group(1).upper(),
                      "numero_oficial": m.group(2).strip()})
    return casos, recusadas


def _linhas_de_tabela(linhas: list[list], mapa: dict | None) -> tuple[list[dict], list, list]:
    if not linhas:
        return [], [], []
    campos, ignorados = _mapear(linhas[0], mapa)
    if "jurisdicao" not in campos.values() or "numero_oficial" not in campos.values():
        return [], ignorados, ["cabecalho sem coluna de pais e/ou de numero"]
    casos, recusadas = [], []
    for ln in linhas[1:]:
        c = {campo: ln[i] for i, campo in campos.items() if i < len(ln)}
        if not str(c.get("jurisdicao") or "").strip() or not str(c.get("numero_oficial") or "").strip():
            if any(str(v or "").strip() for v in ln):
                recusadas.append("; ".join(str(v) for v in ln if str(v or "").strip()))
            continue
        casos.append(c)
    return casos, ignorados, recusadas


def ler(origem: str, mapa: dict | None = None) -> dict:
    """Le XLSX, CSV ou lista colada. Devolve casos crus e o que NAO entendeu.

    Nunca ingere em silencio: coluna nao reconhecida e linha recusada voltam
    nomeadas. Uma carteira que entra com 40 de 59 linhas sem avisar e pior que uma
    que falha -- o quadro sai completo na aparencia e furado no conteudo.
    """
    p = Path(origem)
    if p.exists() and p.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        ws = load_workbook(p, data_only=True, read_only=True).active
        linhas = [list(r) for r in ws.iter_rows(values_only=True)]
        casos, ignorados, recusadas = _linhas_de_tabela(linhas, mapa)
        return {"formato": "xlsx", "casos": casos,
                "colunas_ignoradas": ignorados, "linhas_recusadas": recusadas}

    bruto = p.read_text(encoding="utf-8-sig") if p.exists() else str(origem)
    cabecalho = bruto.splitlines()[0] if bruto.strip() else ""
    # E tabela se QUALQUER celula do cabecalho for reconhecida -- nao so a primeira.
    # Olhar so a primeira jogava para o parser de texto solto toda planilha que
    # comeca por 'Nosso Ref' ou que usa tab como separador.
    celulas = re.split(r"[,;\t]", cabecalho)
    if any(_CAMPO_POR_SINONIMO.get(_chave_coluna(c)) for c in celulas):
        try:
            dialeto = csv.Sniffer().sniff(bruto[:2000], delimiters=",;\t")
        except csv.Error:
            dialeto = csv.excel
        linhas = [r for r in csv.reader(io.StringIO(bruto), dialeto)]
        casos, ignorados, recusadas = _linhas_de_tabela(linhas, mapa)
        return {"formato": "csv", "casos": casos,
                "colunas_ignoradas": ignorados, "linhas_recusadas": recusadas}

    casos, recusadas = _linhas_de_texto(bruto)
    return {"formato": "texto", "casos": casos,
            "colunas_ignoradas": [], "linhas_recusadas": recusadas}


# --------------------------------------------------------------------------- #
# gravacao
# --------------------------------------------------------------------------- #

def gravar(cliente: str, casos: list[dict], fonte: str,
           confianca: str = "informado", hoje: date | None = None) -> int:
    """Grava (ou atualiza) casos de UMA fonte. Nao toca no que veio das outras."""
    if fonte not in FONTES:
        raise ValueError(f"fonte deve ser uma de {sorted(FONTES)}")
    hoje = hoje or date.today()
    c = con()
    n = 0
    for caso in casos:
        j = str(caso.get("jurisdicao") or "").strip().upper()
        num = str(caso.get("numero_oficial") or "").strip()
        norm = normalizar_numero(j, num)
        if not j or not norm:
            continue
        c.execute(
            """INSERT OR REPLACE INTO casos
               (cliente, jurisdicao, numero_norm, fonte, numero_oficial, familia, tipo,
                data_prioridade, data_deposito, data_base, data_concessao, numero_pct,
                equivalente_br, status, confianca, visto_em, nota)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [cliente, j, norm, fonte, num,
             caso.get("familia"), caso.get("tipo"),
             _data(caso.get("data_prioridade")), _data(caso.get("data_deposito")),
             _data(caso.get("data_base")) or _data(caso.get("data_deposito")),
             _data(caso.get("data_concessao")), caso.get("numero_pct"),
             caso.get("equivalente_br"), caso.get("status"),
             confianca, hoje, caso.get("nota")],
        )
        n += 1
    c.close()
    return n


def ingerir(origem: str, cliente: str, mapa: dict | None = None,
            hoje: date | None = None) -> dict:
    """Le a lista do escritorio e grava como fonte 'lista'."""
    lido = ler(origem, mapa)
    gravados = gravar(cliente, lido["casos"], fonte="lista", hoje=hoje)
    lidas = len(lido["casos"]) + len(lido["linhas_recusadas"])
    return {
        "cliente": cliente,
        "formato": lido["formato"],
        "linhas_lidas": lidas,
        "casos_gravados": gravados,
        "colunas_ignoradas": lido["colunas_ignoradas"],
        "linhas_recusadas": lido["linhas_recusadas"],
        "aviso": (
            f"{lidas - gravados} de {lidas} linhas NAO entraram na carteira."
            if gravados < lidas else ""
        ),
    }


# --------------------------------------------------------------------------- #
# descoberta
# --------------------------------------------------------------------------- #

def descobrir_inpi(cliente: str, titular: str | None = None,
                   hoje: date | None = None) -> dict:
    """Casos BR que a base do INPI conhece para este titular."""
    from inpi import inpi_mcp as m

    estados, total = m._carregar_lote(titular=titular or cliente)
    casos = [
        {"jurisdicao": "BR", "numero_oficial": n,
         "data_deposito": e["data_deposito"],
         "status": "encerrado" if e["encerrado_em"] else "ativo"}
        for n, e in estados.items()
    ]
    n = gravar(cliente, casos, fonte="inpi", confianca="calculado", hoje=hoje)
    return {
        "cliente": cliente, "titular_buscado": titular or cliente,
        "casos_gravados": n, "casados_pelo_criterio": total,
        "aviso": (
            "Busca por nome do depositante. Titular estrangeiro e grafia variante "
            "podem ficar de fora -- confira com inpi_titular_resolver. Ausencia aqui "
            "nao e prova de que o caso nao existe."
        ),
    }


def expandir_familia(cliente: str, teto: int = 100,
                     hoje: date | None = None) -> dict:
    """Equivalentes no exterior, pela familia INPADOC dos casos BR ativos.

    'teto' e obrigatorio por causa da cota: o free tier do EPO e 4 GB/semana e nao
    ha contador na API. Uma carteira grande expandida sem limite estoura a semana
    inteira numa chamada. O que ficou de fora volta nomeado, nunca em silencio.
    """
    from familia_epo import familia

    c = con(read_only=True)
    brs = [r[0] for r in c.execute(
        """SELECT DISTINCT numero_norm FROM casos
           WHERE cliente = ? AND jurisdicao = 'BR'
             AND (status IS NULL OR status <> 'encerrado')
           ORDER BY 1""", [cliente]).fetchall()]
    c.close()

    alvo, fora = brs[:teto], brs[teto:]
    casos, erros = [], []
    for num in alvo:
        fam = familia(num)
        if fam.get("erro"):
            erros.append(num)
            continue
        for mb in fam.get("membros", []):
            if mb["pais"] in ("BR", "WO") or not mb.get("data_deposito"):
                continue
            casos.append({
                "jurisdicao": mb["pais"],
                "numero_oficial": mb["referencia"],
                "familia": fam.get("familia_id"),
                "data_deposito": mb.get("data_deposito"),
                "data_concessao": mb.get("data_publicacao") if mb.get("concedida") else None,
                "equivalente_br": num,
                "tipo": "EP-nac" if (mb.get("kind") or "").upper().startswith("T") else None,
            })
    n = gravar(cliente, casos, fonte="inpadoc", confianca="estimado", hoje=hoje)
    return {
        "cliente": cliente, "casos_br_consultados": len(alvo),
        "membros_gravados": n,
        "familias_com_erro": erros,
        "nao_consultados_pelo_teto": fora,
        "aviso": (
            (f"{len(fora)} casos BR ficaram fora pelo teto de {teto}. " if fora else "")
            + (f"{len(erros)} familias nao vieram do EPO. " if erros else "")
            + "A familia INPADOC NAO ve validacao de patente europeia em BE, FR, GB, GR, "
              "IE, IT, LU, NL e SE: o Acordo de Londres dispensa a traducao, entao nao ha "
              "publicacao nacional e nao existe membro de familia. Esses casos so entram "
              "pela lista do escritorio."
        ),
    }


# --------------------------------------------------------------------------- #
# validacao de patente europeia
# --------------------------------------------------------------------------- #

# Estados onde a validacao de um EP nao gera publicacao nacional. Lista herdada de
# carteira_manual.py, onde vivia so na prosa do docstring. Segue a mesma disciplina
# das demais regras estrangeiras: NAO REVISADA -- o Acordo de Londres tem adesoes
# posteriores e regimes parciais (traducao so das reivindicacoes), e quem assina a
# lista e o profissional habilitado, nao este arquivo.
LONDRES = ("BE", "FR", "GB", "GR", "IE", "IT", "LU", "NL", "SE")

# Art. 65 EPC: o estado pode exigir traducao em prazo proprio; 3 meses da mencao de
# concessao e o mais comum. Tambem NAO REVISADO.
VALIDACAO_EP_MESES = 3


def _publicacoes_ep(cliente: str) -> tuple[dict, dict]:
    """({familia: numero da publicacao EP}, {familia: jurisdicoes ja na carteira}).

    SO linha de validacao ('EP-nac') carrega o numero da publicacao EP -- e o mesmo
    em todos os estados validados. Aceitar qualquer numero de 7 digitos pegava numero
    canadense (CA 3282304) e consultava o EPO com ele.
    """
    c = con(read_only=True)
    linhas = c.execute(
        """SELECT familia, jurisdicao, numero_norm, tipo FROM casos
           WHERE cliente = ? AND familia IS NOT NULL AND upper(familia) LIKE 'EP%'""",
        [cliente]).fetchall()
    c.close()
    pubs, jurs = {}, {}
    for fam, j, norm, tipo in linhas:
        jurs.setdefault(fam, set()).add(j)
        if (tipo or "").upper() == "EP-NAC" and norm.isdigit() and len(norm) == 7:
            pubs[fam] = norm
    return pubs, jurs


def descobrir_validacoes(cliente: str, teto: int = 20,
                         hoje: date | None = None) -> dict:
    """Descobre em QUE PAISES um EP foi validado -- inclusive nos de Londres.

    Isto derruba a premissa que estava escrita em carteira_manual.py: e verdade que a
    validacao em BE, FR, GB, GR, IE, IT, LU, NL e SE nao gera publicacao nacional e
    portanto nao existe membro de familia INPADOC. Mas o escritorio nacional REPORTA
    ao EPO o pagamento da anuidade, e esse evento (PGFP) aparece no status legal
    INPADOC -- que e outro servico, que o projeto nao usava.

    Medido contra um docketing real (familia EP14874476): dos 15 estados europeus da
    lista do escritorio, o status legal achou os 15, incluindo os 9 de Londres. E
    achou um a mais, PT, que a lista nao tinha.

    O que continua invisivel por aqui e o que nao e europeu (AU, CA, CN, IN, UA, ZA);
    esses vem pela familia INPADOC, em expandir_familia.
    """
    from epo import epo_mcp

    pubs, _ = _publicacoes_ep(cliente)
    alvo = sorted(pubs.items())[:teto]
    casos, sem_status, achados = [], [], {}
    for fam, pub in alvo:
        legal = epo_mcp.epo_status_legal(f"EP{pub}")
        if not legal.get("encontrado"):
            sem_status.append(fam)
            continue
        reg = epo_mcp.epo_register(f"EP{pub}")
        base = _data(reg.get("data_deposito"))
        conc = _data(reg.get("mencao_de_concessao"))
        pagos = set(legal["taxa_nacional_paga_em"])
        caducados = set(legal["caducado_em"])
        achados[fam] = sorted(pagos)
        for pais, st in legal["por_pais"].items():
            if pais not in pagos and not st["atos"]:
                continue
            casos.append({
                # numero NACIONAL puro, sem o prefixo 'EP': e assim que a validacao e
                # numerada em cada estado, e e assim que a lista do escritorio traz.
                # Com 'EP3088824' a mesma validacao virava dois casos.
                "jurisdicao": pais, "numero_oficial": pub, "familia": fam,
                "tipo": "EP-nac", "data_base": base, "data_deposito": base,
                "data_concessao": conc,
                "status": "caducado" if pais in caducados else "ativo",
                # PGFP e o escritorio nacional dizendo que a anuidade foi paga; REG
                # sozinho so diz que houve ato la, e o codigo nacional pode ser ate
                # de extincao. Nao sao a mesma evidencia e nao vao com o mesmo rotulo.
                "nota": ("anuidade paga ao escritorio nacional (PGFP)" if pais in pagos
                         else f"{st['atos']} ato(s) nacional(is) (REG) — natureza a conferir"),
            })
    n = gravar(cliente, casos, fonte="inpadoc-legal", confianca="estimado", hoje=hoje)
    return {
        "cliente": cliente,
        "familias_consultadas": len(alvo),
        "casos_gravados": n,
        "validacoes_por_familia": achados,
        "sem_status_legal": sem_status,
        "nao_consultadas_pelo_teto": sorted(pubs)[teto:],
        "aviso": (
            "PGFP e afirmacao do escritorio nacional de que a anuidade foi paga; REG "
            "sozinho so diz que houve ato no pais. Ausencia de evento NAO prova "
            "ausencia de validacao -- pode ser atraso do escritorio em reportar. E o "
            "que nao e europeu nao aparece aqui: use expandir_familia."
        ),
    }


def validacoes_ep(cliente: str, teto: int = 20) -> dict:
    """Prazo de validacao do art. 65 e a lacuna de Londres -- por familia EP.

    UMA linha por familia, nao uma por pais designado: desde 2009 o deposito designa
    os ~39 estados contratantes de uma vez, entao tratar designados como candidatos
    inventaria 39 casos por patente. O que esta funcao devolve e a pergunta util:
    dos estados de Londres que foram designados, em quais a carteira NAO tem
    registro? Se houve validacao la, nenhuma fonte publica mostra.
    """
    from epo import epo_mcp
    from inpi.anuidades import _mais_meses

    pubs, jurs = _publicacoes_ep(cliente)
    familias = sorted(set(pubs) | set(jurs))

    saida, sem_publicacao = [], []
    for fam in familias[:teto]:
        pub = pubs.get(fam)
        tem = jurs.get(fam, set())
        if not pub:
            sem_publicacao.append(fam)
            continue
        reg = epo_mcp.epo_register(f"EP{pub}")
        if not reg.get("encontrado"):
            saida.append({"familia": fam, "ep": f"EP{pub}",
                          "situacao": "nao encontrado no European Patent Register"})
            continue
        mencao = _data(reg.get("mencao_de_concessao"))
        designados = set(reg.get("estados_designados") or ())
        # Sem mencao de concessao o EP ainda esta em exame: nao ha o que validar, e
        # apontar 9 estados de Londres como lacuna seria inventar duvida sobre um
        # ato que ainda nao podia ter acontecido.
        lacuna = sorted((set(LONDRES) & designados) - tem) if mencao else []
        saida.append({
            "familia": fam,
            "ep": f"EP{pub}",
            "situacao_no_register": reg.get("situacao"),
            "mencao_de_concessao": mencao.isoformat() if mencao else None,
            "prazo_de_validacao": (
                _mais_meses(mencao, VALIDACAO_EP_MESES).isoformat() if mencao else None),
            "confianca": "estimado",
            "estados_com_registro_na_carteira": sorted(tem),
            "estados_de_londres_sem_registro": lacuna,
            "pergunta_para_o_associado": (
                f"Houve validacao em {', '.join(lacuna)}? Nestes estados o Acordo de "
                "Londres dispensa a traducao, entao a validacao nao gera publicacao "
                "nacional e nao aparece em fonte publica nenhuma."
            ) if lacuna else "",
        })

    return {
        "cliente": cliente,
        "familias_ep": len(familias),
        "consultadas": len(saida),
        "sem_numero_de_publicacao_ep": sem_publicacao,
        "validacoes": saida,
        "aviso": (
            f"Prazo do art. 65 EPC calculado como {VALIDACAO_EP_MESES} meses da mencao "
            "de concessao. REGRA NAO REVISADA: cada estado tem regime proprio e ha "
            "estados que exigem traducao parcial. Confirme com o associado local. A "
            "mencao de concessao, essa sim, e dado oficial do European Patent Register."
        ),
    }


# --------------------------------------------------------------------------- #
# leitura consolidada
# --------------------------------------------------------------------------- #

# Quem vale mais quando as fontes divergem em um campo. A lista do escritorio ganha
# porque e a unica que conhece o caso inteiro; o INPI ganha do INPADOC no Brasil
# porque e a fonte primaria. Isso escolhe o VALOR EXIBIDO -- a divergencia continua
# registrada e sinalizada.
PRIORIDADE = {"lista": 0, "inpi": 1, "epo-register": 2, "inpadoc-legal": 3, "inpadoc": 4}

_CAMPOS = ("numero_oficial", "familia", "tipo", "data_prioridade", "data_deposito",
           "data_base", "data_concessao", "numero_pct", "equivalente_br", "status", "nota")


def listar(cliente: str, jurisdicoes: list[str] | None = None) -> dict:
    """A carteira consolidada, com a divergencia entre fontes a vista."""
    c = con(read_only=True)
    sql = "SELECT * FROM casos WHERE cliente = ?"
    params: list = [cliente]
    if jurisdicoes:
        sql += " AND jurisdicao IN (SELECT unnest(?::VARCHAR[]))"
        params.append([j.strip().upper() for j in jurisdicoes])
    cur = c.execute(sql + " ORDER BY jurisdicao, numero_norm", params)
    cols = [d[0] for d in cur.description]
    linhas = [dict(zip(cols, r)) for r in cur.fetchall()]
    c.close()

    grupos: dict = {}
    for l in linhas:
        # Uma validacao de EP e UMA por estado dentro da familia, e cada fonte a
        # numera de um jeito: a lista do escritorio usa o numero do PEDIDO europeu
        # (ES 15868739) e o INPADOC usa o da PUBLICACAO (ES 3235912). Casar so pelo
        # numero duplicava a mesma validacao. Fora do EP-nac vale o numero, porque
        # ali dois casos no mesmo pais e na mesma familia sao mesmo dois casos
        # (divisional, continuacao).
        if (l["tipo"] or "").upper() == "EP-NAC" and l["familia"]:
            chave = (l["jurisdicao"], "fam:" + l["familia"])
        else:
            chave = (l["jurisdicao"], l["numero_norm"])
        grupos.setdefault(chave, []).append(l)

    casos, conflitos = [], []
    for (j, norm), fontes in sorted(grupos.items()):
        fontes.sort(key=lambda x: PRIORIDADE.get(x["fonte"], 9))
        caso = {"jurisdicao": j, "numero_norm": norm,
                "fontes": [f["fonte"] for f in fontes]}
        for campo in _CAMPOS:
            caso[campo] = next((f[campo] for f in fontes if f[campo] not in (None, "")), None)
        for campo in ("data_base", "data_deposito", "data_concessao"):
            vistos = {f["fonte"]: f[campo] for f in fontes if f[campo]}
            if len(set(vistos.values())) > 1:
                conflitos.append({"jurisdicao": j, "numero_norm": norm,
                                  "campo": campo, "por_fonte": {k: str(v) for k, v in vistos.items()}})
                caso["conflito"] = True
        caso["visto_em"] = max((f["visto_em"] for f in fontes if f["visto_em"]), default=None)
        casos.append(caso)

    visto = [c_["visto_em"] for c_ in casos if c_["visto_em"]]
    return {
        "cliente": cliente,
        "total": len(casos),
        "por_jurisdicao": {j: sum(1 for c_ in casos if c_["jurisdicao"] == j)
                           for j in sorted({c_["jurisdicao"] for c_ in casos})},
        "por_fonte": {f: sum(1 for l in linhas if l["fonte"] == f)
                      for f in sorted({l["fonte"] for l in linhas})},
        "sem_data_base": [c_["numero_oficial"] for c_ in casos if not c_["data_base"]],
        "conflitos": conflitos,
        "carteira_vista_em": {"mais_antigo": str(min(visto)) if visto else None,
                              "mais_recente": str(max(visto)) if visto else None},
        "casos": casos,
    }


# --------------------------------------------------------------------------- #
# panorama -- a pergunta "quais os prazos do cliente X"
# --------------------------------------------------------------------------- #

def panorama(cliente: str, de: str | None = None, ate: str | None = None,
             jurisdicoes: list[str] | None = None,
             incluir_validacao_ep: bool = True, teto_ep: int = 20) -> dict:
    """Todos os prazos de um cliente: Brasil e exterior, pais grande e pais pequeno.

    Monta sobre o que ja existe -- nao reimplementa regra nenhuma. O Brasil sai de
    inpi_prazos_carteira (art. 84 calibrado); o exterior sai da tabela de regras por
    jurisdicao; a validacao de EP sai do European Patent Register.

    A secao 'lacunas' e obrigatoria e nunca vem vazia por conveniencia: e ela que
    impede a leitura de que o quadro esta completo quando nao esta.
    """
    from inpi import quadro_global as qg

    d_hoje = date.fromisoformat(de) if de else date.today()
    d_ate = date.fromisoformat(ate) if ate else _mais_um_ano(d_hoje)

    cart = listar(cliente, jurisdicoes=jurisdicoes)
    prazos: list[dict] = []
    lacunas: dict = {
        "casos_sem_data_base": cart["sem_data_base"],
        "conflitos_entre_fontes": cart["conflitos"],
        "carteira_vista_em": cart["carteira_vista_em"],
    }

    # --- Brasil: a fonte calibrada ---
    brs = [c["numero_norm"] for c in cart["casos"] if c["jurisdicao"] == "BR"]
    if brs:
        try:
            from inpi import inpi_mcp as m
            br = m.inpi_prazos_carteira(numeros=brs, de=d_hoje.isoformat(),
                                        ate=d_ate.isoformat(), limite_resultados=5000)
            for p in br["prazos"]:
                prazos.append({
                    "jurisdicao": "BR", "numero_oficial": f"BR {p['numero_inpi']}",
                    "tipo": p.get("tipo"), "descricao": p.get("descricao"),
                    "prazo": p["prazo"], "situacao": p.get("status"),
                    "confianca": "calculado", "fonte": "INPI — LPI art. 84",
                })
        except Exception as e:
            lacunas["brasil_nao_consultado"] = (
                f"{len(brs)} casos BR nao tiveram prazo calculado: {e}. "
                "Ausencia aqui NAO significa que nao ha prazo."
            )

    # --- Exterior: a tabela de regras ---
    sem_regra, nao_revisadas = set(), set()
    caducados = 0
    for c in cart["casos"]:
        j = c["jurisdicao"]
        if j == "BR":
            continue
        # O escritorio nacional ja comunicou a extincao (PG25). Projetar anuidade de
        # patente extinta e o mesmo erro que o codigo brasileiro evita com os
        # despachos terminais: manda pagar o que nao existe mais.
        if c.get("status") == "caducado":
            caducados += 1
            continue
        base = c["data_base"] or c["data_deposito"]
        # 'T*' e o kind de traducao de EP validado -- e o que faz _regra_de usar a
        # regra EP-nac em vez da nacional generica.
        kind = "T1" if (c.get("tipo") or "").upper().startswith("EP-NAC") else None
        for a in qg._anuidades_estrangeiras(j, base, d_hoje, d_ate,
                                            data_concessao=c["data_concessao"],
                                            kind=kind):
            if a["confianca"] == "sem_regra":
                sem_regra.add(j)
                continue
            if a["confianca"] in ("indisponivel", "sem_anuidade_nesta_fase"):
                continue
            if a["confianca"] != "calculado":
                nao_revisadas.add(j)
            prazos.append({
                "jurisdicao": j, "numero_oficial": c["numero_oficial"],
                "tipo": "anuidade", "descricao": f"{a['anuidade']}a anuidade",
                "prazo": a["vencimento"], "fim_com_graca": a.get("fim_com_graca"),
                "situacao": "a vencer" if a["vencimento"] >= d_hoje.isoformat()
                            else "VENCIDA — ainda no prazo de graca",
                "confianca": a["confianca"], "fonte": a["nota"],
                "familia": c.get("familia"),
            })

    lacunas["jurisdicoes_fora_da_tabela_de_regras"] = sorted(sem_regra)
    lacunas["jurisdicoes_com_regra_nao_revisada"] = sorted(nao_revisadas)
    if caducados:
        lacunas["casos_caducados_fora_do_quadro"] = (
            f"{caducados} casos nao entram: o escritorio nacional ja comunicou a "
            "extincao ao EPO (evento PG25). Veja-os em carteira_listar."
        )

    # --- Validacao de patente europeia ---
    if incluir_validacao_ep:
        v = validacoes_ep(cliente, teto=teto_ep)
        perguntas = []
        for item in v["validacoes"]:
            if item.get("prazo_de_validacao") and \
                    d_hoje.isoformat() <= item["prazo_de_validacao"] <= d_ate.isoformat():
                prazos.append({
                    "jurisdicao": "EP", "numero_oficial": item["ep"],
                    "tipo": "validacao_ep", "descricao": "validacao nacional (art. 65 EPC)",
                    "prazo": item["prazo_de_validacao"], "situacao": "a vencer",
                    "confianca": item["confianca"], "fonte": "European Patent Register",
                    "familia": item["familia"],
                })
            if item.get("estados_de_londres_sem_registro"):
                perguntas.append({"ep": item["ep"],
                                  "estados": item["estados_de_londres_sem_registro"]})
        if perguntas:
            lacunas["validacao_ep_possivelmente_invisivel"] = perguntas
        if v["sem_numero_de_publicacao_ep"]:
            lacunas["familias_ep_sem_numero_de_publicacao"] = v["sem_numero_de_publicacao_ep"]

    prazos.sort(key=lambda p: (p["prazo"] or "9999", p["jurisdicao"], p["numero_oficial"]))
    return {
        "cliente": cliente,
        "de": d_hoje.isoformat(),
        "ate": d_ate.isoformat(),
        "casos_na_carteira": cart["total"],
        "total_de_prazos": len(prazos),
        "por_confianca": _conta(prazos, "confianca"),
        "por_tipo": _conta(prazos, "tipo"),
        "por_jurisdicao": _conta(prazos, "jurisdicao"),
        "lacunas": lacunas,
        "aviso": (
            "PROJECAO, NAO FATURA. As bases sao registro do passado: nenhuma publica "
            "calendario de vencimento futuro. 'calculado' e a regra brasileira do art. "
            "84, calibrada contra 285.409 despachos; 'estimado' e regra estrangeira "
            "transcrita da legislacao e NAO revisada por profissional habilitado. Leia "
            "'lacunas' antes de tratar este quadro como completo -- o controle de prazo "
            "continua sendo do docketing e do procurador."
        ),
        "prazos": prazos,
    }


# --------------------------------------------------------------------------- #
# fila de revisao de jurisdicao
# --------------------------------------------------------------------------- #

# As quatro perguntas que decidem se uma data projetada esta certa. Sao as mesmas
# quatro em que a implementacao ja errou pelo menos uma vez em alguma jurisdicao.
PERGUNTAS_DE_REVISAO = (
    "A anuidade conta do DEPOSITO ou da CONCESSAO? (em JP e KR a 1a a 3a sao pagas "
    "de uma vez na concessao)",
    "Qual e a PRIMEIRA anuidade devida? (BR 3a, GB 5a, AU 5a, CL 10a...)",
    "Qual o prazo de GRACA com sobretaxa, e ha restauracao depois dele?",
    "O vencimento e no dia do aniversario ou no ULTIMO DIA DO MES? (EP, DE, FR, GB e "
    "ZA usam fim de mes; hoje isso vive chumbado em carteira_manual.py, fora da tabela)",
)


def a_revisar(cliente: str | None = None) -> dict:
    """Fila de jurisdicoes a assinar, ordenada pelo peso na carteira real.

    Revisar por ordem alfabetica ou por tamanho do pais desperdica o esforco: o que
    decide a prioridade e quantos casos do cliente dependem daquela regra. Assinar
    uma jurisdicao (revisado_por + revisado_em no CSV) converte as linhas dela de
    'estimado' para 'calculado' sem tocar em codigo.
    """
    from inpi import jurisdicoes as jur

    regras = jur.carregar()
    contagem: dict = {}
    if cliente:
        c = con(read_only=True)
        for j, tipo, n in c.execute(
                """SELECT jurisdicao, tipo, count(DISTINCT numero_norm) FROM casos
                   WHERE cliente = ? GROUP BY 1, 2""", [cliente]).fetchall():
            # caso 'EP-nac' depende da regra EP-NAC, nao da nacional do pais
            alvo = "EP-NAC" if (tipo or "").upper() == "EP-NAC" else j.upper()
            contagem[alvo] = contagem.get(alvo, 0) + n
        c.close()

    fila = []
    for j, n in sorted(contagem.items(), key=lambda x: -x[1]):
        r = regras.get(j)
        if not r:
            fila.append({"jurisdicao": j, "casos_na_carteira": n,
                         "situacao": "FORA DA TABELA — nenhuma regra existe",
                         "acao": f"criar a linha '{j}' em anuidades-por-jurisdicao.csv"})
            continue
        if r.projeta:
            continue
        fila.append({
            "jurisdicao": j, "casos_na_carteira": n, "nome": r.nome,
            "situacao": "NAO REVISADA — projeta com rotulo 'estimado'",
            "regra_atual": {
                "data_base": r.data_base, "primeira": r.primeira,
                "periodicidade": r.periodicidade, "marcos": r.marcos,
                "dias_apos_concessao": r.dias_apos_concessao,
                "graca_meses": r.graca_meses, "vigencia_anos": r.vigencia_anos,
            },
            "base_legal": r.base_legal,
            "fonte_atual": r.fonte,
            "confirmar": list(PERGUNTAS_DE_REVISAO),
            "para_liberar": (
                f"preencha 'revisado_por' e 'revisado_em' na linha '{j}' de "
                "inpi/referencias/anuidades-por-jurisdicao.csv"
            ),
        })

    return {
        "cliente": cliente,
        "a_revisar": fila,
        "ja_assinadas": sorted(j for j, r in regras.items() if r.projeta),
        "lacunas_estruturais_da_tabela": [
            "BE, FR, GR, IE, IT, LU, NL e SE nao tem linha nacional. Sao justamente os "
            "estados do Acordo de Londres: um caso la so e projetado se vier marcado "
            "tipo='EP-nac', que roteia para a regra EP-NAC.",
            "'EP-nac' e UMA linha generica (primeira=3, contada do deposito), mas a "
            "linha 'GB' do mesmo CSV diz primeira=5. Um EP validado no Reino Unido nao "
            "segue a generica — falta excecao por pais.",
        ],
        "aviso": (
            "Esta fila e insumo de revisao, nao revisao. Quem assina e o profissional "
            "habilitado; o preenchimento de 'revisado_por' e a assinatura."
        ),
    }


def _mais_um_ano(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29/02
        return d.replace(year=d.year + 1, day=28)


def _conta(linhas: list[dict], campo: str) -> dict:
    return {str(v): sum(1 for l in linhas if l.get(campo) == v)
            for v in sorted({l.get(campo) for l in linhas}, key=str)}
