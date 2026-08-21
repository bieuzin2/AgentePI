"""Motor de estatistica GENERICO sobre os dados do INPI/pePI, com guarda-corpos.

Existe para resolver uma falha real: o agente sabia CONTAR anuidades pagas
(inpi_anuidades_pagas) mas nao conseguia SOMAR/tirar media do VALOR pago -- a
pergunta "quanto a Clarke gastou em anuidades em marco/2025 vs marco/2026" nao
tinha resposta. Aqui uma unica tool soma/media/mediana/min/max/contagem sobre os
datasets que temos, com filtro por escritorio/titular/CPC/periodo e comparativo
lado a lado entre bancas.

NAO e SQL livre: dataset, metrica e agrupar_por sao WHITELIST rigida (dicts
abaixo). O usuario nunca injeta tabela/coluna -- so escolhe entre chaves
conhecidas, e todo filtro vai parametrizado. O motivo do guarda-corpo e o mesmo
das outras tools: banco read-only, e uma metrica de valor sobre a coluna errada
mente com cara de numero.

VALOR e LIXO: os ledgers guardam valor como texto sujo -- em ~18 linhas o numero
da GRU vazou para o campo valor e estoura qualquer soma (bilhoes). A regra de
descarte e a MESMA de inpi/valores.py (parse_valor), replicada em SQL por
desempenho: limpa '$'/espaco/virgula, TRY_CAST, e descarta < 0 ou > TETO_SANO. O
que foi descartado e contado em `descartados_invalidos` -- nunca somado.

COBERTURA: os datasets de valor (anuidades_pagas/peticoes) so existem para os
pedidos que a coleta da ficha raspou (bancas alvo). Fora desse escopo o ledger
vem vazio: total 0 significa "nao coletado", NUNCA "gastou zero". Toda saida de
valor declara a cobertura, no mesmo espirito de inpi/anuidades_pagas.py.
"""

from __future__ import annotations

from inpi import escritorios as esc
from inpi.anuidades_pagas import _norm_periodo
from inpi.consulta import _linhas, _tem_tabela
from inpi.mercado import _CODIGOS_EXIGENCIA
from inpi.valores import MOEDA, TETO_SANO

# --- WHITELIST DE DATASETS -------------------------------------------------
# Cada dataset mapeia a tabela base, a expressao de DATA (normalizada a um
# timestamp/date de onde strftime extrai mes/ano) e, se houver, a coluna de VALOR
# e a de CODIGO. `where` extra e filtro fixo do dataset (ex.: so anuidade paga, so
# codigos de exigencia). `distinct` conta numero_inpi distintos (depositos).
_DATASETS: dict[str, dict] = {
    "anuidades_pagas": {
        "tabela": "ficha_anuidades",
        "dt": "try_strptime(data_pagamento, '%d/%m/%Y')",
        "valor": "valor",
        "codigo": "numero",
        # data_pagamento preenchida = efetivamente paga (idem anuidades_pagas.py).
        "where": "data_pagamento IS NOT NULL AND data_pagamento <> ''",
        "tem_valor": True,
    },
    "peticoes": {
        "tabela": "ficha_peticoes",
        "dt": "try_strptime(data_protocolo, '%d/%m/%Y')",
        "valor": "valor",
        "codigo": "codigo",
        "where": "data_protocolo IS NOT NULL AND data_protocolo <> ''",
        "tem_valor": True,
    },
    "exigencias": {
        "tabela": "despachos",
        "dt": "data_rpi",  # ja e DATE
        "valor": None,
        "codigo": "codigo_despacho",
        # so os despachos de exigencia EMITIDA (6.1/2.5/7.1), ver inpi/mercado.py.
        "where": "codigo_despacho IN ("
        + ",".join(f"'{c}'" for c in _CODIGOS_EXIGENCIA)
        + ")",
        "tem_valor": False,
    },
    "depositos": {
        "tabela": "biblio",
        "dt": "data_deposito",  # ja e DATE
        "valor": None,
        "codigo": None,
        "where": None,
        "tem_valor": False,
        "distinct": True,  # conta pedidos (numero_inpi distintos)
    },
}

_METRICAS_VALOR = {"soma_valor", "media_valor", "mediana_valor", "min_valor", "max_valor"}
_METRICAS = {"contagem", *_METRICAS_VALOR}
_AGRUPAR = {"mes", "ano", "codigo", "cpc", "escritorio", "titular"}

# Expressao que limpa o valor-texto e o converte a DOUBLE, replicando a regra de
# parse_valor (inpi/valores.py): remove 'R'/'$'/espaco, remove virgula (separador
# de milhar), TRY_CAST. Devolve NULL para lixo/vazio.
_VAL_CLEAN = (
    "TRY_CAST(replace(regexp_replace(COALESCE(valor,''), "
    "'[R$[:space:]]', '', 'g'), ',', '') AS DOUBLE)"
)
# Valor sano = dentro de [0, TETO_SANO]; fora disso e GRU vazada / lixo -> NULL.
_V_SANO = f"CASE WHEN val_clean >= 0 AND val_clean <= {TETO_SANO} THEN val_clean END"


def _alvo_escritorio_sql() -> str:
    """Subquery dos numero_inpi de um escritorio (padrao EXATO de
    anuidades_pagas.py): procuradores -> escritorios pela chave canonica."""
    return (
        "SELECT DISTINCT p.numero_inpi FROM procuradores p "
        "JOIN escritorios e ON e.original = p.procurador WHERE e.chave = ?"
    )


def _dim_join(agrupar_por: str) -> tuple[str, str]:
    """(join, coluna_de_grupo) para agrupamentos que exigem dimensao externa.
    Usamos DISTINCT (numero_inpi, chave/classe) para nao multiplicar linhas do
    ledger por grafia repetida de procurador/depositante."""
    if agrupar_por == "cpc":
        return (
            "JOIN (SELECT DISTINCT numero_inpi, substr(simbolo,1,4) AS g "
            "FROM ipc) d ON d.numero_inpi = base.numero_inpi",
            "d.g",
        )
    if agrupar_por == "escritorio":
        return (
            "JOIN (SELECT DISTINCT p.numero_inpi, e.chave AS g FROM procuradores p "
            "JOIN escritorios e ON e.original = p.procurador) d "
            "ON d.numero_inpi = base.numero_inpi",
            "d.g",
        )
    # titular
    return (
        "JOIN (SELECT DISTINCT dp.numero_inpi, t.chave AS g FROM depositantes dp "
        "JOIN titulares t ON t.original = dp.depositante) d "
        "ON d.numero_inpi = base.numero_inpi",
        "d.g",
    )


def _metric_expr(metrica: str, ds: dict) -> str:
    """SQL da metrica. As de valor operam sobre o valor SANO (lixo ja e NULL, que
    sum/avg/median ignoram). contagem respeita o distinct do dataset."""
    if metrica == "contagem":
        return "count(DISTINCT numero_inpi)" if ds.get("distinct") else "count(*)"
    col = _V_SANO
    return {
        "soma_valor": f"coalesce(sum({col}), 0)",
        "media_valor": f"avg({col})",
        "mediana_valor": f"median({col})",
        "min_valor": f"min({col})",
        "max_valor": f"max({col})",
    }[metrica]


def _base_cte(ds: dict, chave_esc, chave_tit, cpc, de_iso, ate_iso) -> tuple[str, list]:
    """Monta `WITH raw AS (...), base AS (...)` com as linhas ja filtradas.
    raw normaliza dt/codigo/valor; base aplica os filtros (numero_inpi e periodo).
    Devolve (sql_ctes, params)."""
    sel = [
        "numero_inpi",
        f"{ds['dt']} AS dt",
        f"({ds['codigo']}) AS codigo" if ds["codigo"] else "NULL AS codigo",
    ]
    if ds["tem_valor"]:
        sel.append(f"{ds['valor']} AS valor_raw")
        sel.append(f"{_VAL_CLEAN} AS val_clean")
    raw_where = ds["where"] or "1=1"
    raw = f"raw AS (SELECT {', '.join(sel)} FROM {ds['tabela']} WHERE {raw_where})"

    cond = ["dt IS NOT NULL"]
    params: list = []
    if chave_esc is not None:
        cond.append(f"numero_inpi IN ({_alvo_escritorio_sql()})")
        params.append(chave_esc)
    if chave_tit is not None:
        cond.append(
            "numero_inpi IN (SELECT DISTINCT dp.numero_inpi FROM depositantes dp "
            "JOIN titulares t ON t.original = dp.depositante WHERE t.chave = ?)"
        )
        params.append(chave_tit)
    if cpc:
        cond.append("numero_inpi IN (SELECT numero_inpi FROM ipc WHERE simbolo LIKE ?)")
        params.append(f"{cpc.strip()}%")
    if de_iso:
        cond.append("strftime(dt, '%Y-%m-%d') >= ?")
        params.append(de_iso)
    if ate_iso:
        cond.append("strftime(dt, '%Y-%m-%d') <= ?")
        params.append(ate_iso)

    base = f"base AS (SELECT * FROM raw WHERE {' AND '.join(cond)})"
    return f"WITH {raw}, {base}", params


def _cobertura(chave_esc) -> int:
    """Pedidos com ficha coletada (0 = nao coletado). Escopo ao escritorio se
    houver chave; senao a base inteira de ficha_extras."""
    if not _tem_tabela("ficha_extras"):
        return 0
    if chave_esc is None:
        return _linhas("SELECT count(*) n FROM ficha_extras")[0]["n"]
    return _linhas(
        "SELECT count(*) n FROM ficha_extras fe WHERE fe.numero_inpi IN "
        f"({_alvo_escritorio_sql()})",
        [chave_esc],
    )[0]["n"]


_AVISO_COBERTURA = (
    "So conta o que a coleta da ficha do pePI raspou (bancas alvo). Se "
    "pedidos_com_ficha_coletada for baixo/zero, a coleta NAO cobriu esse escopo -- "
    "total 0 significa 'nao coletado', NUNCA 'gastou zero'. Confirme antes de "
    "afirmar ausencia."
)


def _num(v):
    """Decimal (median) / float -> float com 2 casas; None passa direto."""
    return None if v is None else round(float(v), 2)


def _computar(dataset, metrica, agrupar_por, escritorio, titular, cpc,
              de_iso, ate_iso, top) -> dict:
    """Nucleo: roda a metrica para UM escritorio (ou nenhum). Reutilizado pelo
    comparar_com para cada banca. Assume dataset/metrica/agrupar_por ja validados."""
    ds = _DATASETS[dataset]
    tem_valor = ds["tem_valor"]

    chave_esc = esc.normalizar(escritorio) if escritorio else None
    chave_tit = None
    if titular:
        # best-effort: a base pode nao ter titulares em alguns ambientes.
        try:
            from inpi.titulares import chave_de

            chave_tit = chave_de(titular)
        except Exception:
            chave_tit = None

    ctes, base_params = _base_cte(ds, chave_esc, chave_tit, cpc, de_iso, ate_iso)
    metric_sql = _metric_expr(metrica, ds)

    # Total geral (sem agrupamento) -- serve de `total` e, para valor, carrega a
    # contagem de descartados. base_params vale para o bloco WITH.
    if tem_valor:
        total_sql = (
            f"{ctes} SELECT {metric_sql} AS total, "
            "sum(CASE WHEN valor_raw IS NOT NULL AND trim(valor_raw) <> '' "
            f"AND ({_V_SANO}) IS NULL THEN 1 ELSE 0 END) AS descartados FROM base"
        )
    else:
        total_sql = f"{ctes} SELECT {metric_sql} AS total, 0 AS descartados FROM base"
    tot_row = _linhas(total_sql, base_params)[0]
    total = _num(tot_row["total"]) if metrica != "contagem" else tot_row["total"]
    descartados = int(tot_row["descartados"] or 0)

    resultado: object
    if agrupar_por:
        if agrupar_por in ("mes", "ano"):
            fmt = "%Y-%m" if agrupar_por == "mes" else "%Y"
            grupo, join, order = f"strftime(dt, '{fmt}')", "", "grupo ASC"
        elif agrupar_por == "codigo":
            grupo, join, order = "codigo", "", "valor DESC"
        else:  # cpc / escritorio / titular -> dimensao externa
            join, gcol = _dim_join(agrupar_por)
            grupo, order = gcol, "valor DESC"
        grp_sql = (
            f"{ctes} SELECT {grupo} AS grupo, {metric_sql} AS valor "
            f"FROM base {join} WHERE {grupo} IS NOT NULL "
            f"GROUP BY 1 ORDER BY {order} LIMIT {top}"
        )
        linhas = _linhas(grp_sql, base_params)
        v = (lambda x: x) if metrica == "contagem" else _num
        resultado = [{"chave_do_grupo": r["grupo"], "valor_da_metrica": v(r["valor"])}
                     for r in linhas]
    else:
        resultado = total

    out: dict = {
        "escritorio": escritorio,
        "chave": chave_esc,
        "resultado": resultado,
        "total": total,
    }
    if tem_valor:
        cob = _cobertura(chave_esc)
        out["moeda"] = MOEDA
        out["descartados_invalidos"] = descartados
        # Regra travada: valor so existe com ficha coletada. Cobertura 0 -> nunca
        # devolve 0 silencioso; explica que a banca nao tem ledger de valor.
        if cob == 0:
            out["resultado"] = None
            out["total"] = None
            out["cobertura"] = {
                "pedidos_com_ficha_coletada": 0,
                "aviso": "nao coletado -- sem ledger de valor para este escopo. "
                + _AVISO_COBERTURA,
            }
        else:
            out["cobertura"] = {"pedidos_com_ficha_coletada": cob, "aviso": _AVISO_COBERTURA}
    return out


def _proximas(dataset: str, escritorio, comparar_com) -> list[str]:
    """1-3 follow-ups CONCRETOS que tools REAIS do projeto respondem (seeds para o
    agente sugerir; so cita o que existe)."""
    s = []
    if dataset == "anuidades_pagas":
        s.append("anuidades a vencer no proximo periodo (financeiro_projecao)")
        s.append("contagem de anuidades pagas por mes (inpi_anuidades_pagas)")
    elif dataset == "peticoes":
        s.append("peticoes por codigo, ex. cumprimento de exigencia 207 (inpi_peticoes_escritorio)")
    elif dataset == "exigencias":
        s.append("exigencias emitidas e desfecho por ano (inpi_exigencias_escritorio)")
    else:  # depositos
        s.append("perfil tecnologico/serie de depositos do titular (inpi_perfil_titular / inpi_serie_mercado)")
    if escritorio and not comparar_com:
        s.append("comparar com outra banca (parametro comparar_com)")
    return s[:3]


def inpi_estatistica(dataset: str, metrica: str, agrupar_por: str | None = None,
                     escritorio: str | None = None, titular: str | None = None,
                     cpc: str | None = None, de: str | None = None,
                     ate: str | None = None,
                     comparar_com: str | list[str] | None = None,
                     top: int = 20) -> dict:
    """Soma/media/estatistica GENERICA sobre os dados do INPI, com comparativo entre bancas.

    USE QUANDO: a pergunta pede AGREGAR valor ou contagem -- "quanto a Clarke
    GASTOU em anuidades em marco/2025 vs marco/2026", "valor medio de peticao por
    mes", "quantos depositos por CPC", "comparar duas bancas". Para o detalhe de um
    processo use inpi_processo; para a CONTAGEM simples de anuidade paga de uma
    banca use inpi_anuidades_pagas -- esta tool e o motor de AGREGACAO.

    Datasets: 'anuidades_pagas' e 'peticoes' (tem VALOR -> aceitam soma/media/etc,
    e so cobrem bancas com ficha coletada); 'exigencias' e 'depositos' (SEM valor,
    so contagem, mas sobre a base inteira).

    Args:
        dataset: 'anuidades_pagas' | 'peticoes' | 'exigencias' | 'depositos'.
        metrica: 'contagem' | 'soma_valor' | 'media_valor' | 'mediana_valor' |
            'min_valor' | 'max_valor'. As de valor so valem p/ datasets com valor.
        agrupar_por: 'mes' | 'ano' | 'codigo' | 'cpc' | 'escritorio' | 'titular'.
            Omita para um total unico.
        escritorio: nome da banca (resolvido para a chave canonica).
        titular: nome do depositante (best-effort; a base pode nao ter titulares).
        cpc: prefixo de classificacao (join em ipc, simbolo LIKE prefixo%).
        de/ate: periodo, 'AAAA-MM' ou 'AAAA-MM-DD'.
        comparar_com: outra banca (ou lista) -> roda a MESMA metrica lado a lado.
        top: limite de grupos retornados (default 20).
    """
    if dataset not in _DATASETS:
        return {"erro": True, "mensagem": (
            f"dataset invalido: {dataset!r}. Use um de {sorted(_DATASETS)}.")}
    if metrica not in _METRICAS:
        return {"erro": True, "mensagem": (
            f"metrica invalida: {metrica!r}. Use um de {sorted(_METRICAS)}.")}
    if agrupar_por is not None and agrupar_por not in _AGRUPAR:
        return {"erro": True, "mensagem": (
            f"agrupar_por invalido: {agrupar_por!r}. Use um de {sorted(_AGRUPAR)}.")}

    ds = _DATASETS[dataset]
    if metrica in _METRICAS_VALOR and not ds["tem_valor"]:
        return {"erro": True, "mensagem": (
            f"metrica de valor ({metrica}) nao existe no dataset {dataset!r} -- ele "
            "nao tem coluna de valor. Use 'contagem', ou um dataset com valor "
            "('anuidades_pagas'/'peticoes').")}
    if agrupar_por == "codigo" and not ds["codigo"]:
        return {"erro": True, "mensagem": (
            f"dataset {dataset!r} nao tem coluna de codigo para agrupar.")}

    # Tabela base pode faltar em ambiente sem a coleta (ficha_*). Erro claro.
    if not _tem_tabela(ds["tabela"]):
        return {"erro": True, "mensagem": (
            f"Tabela {ds['tabela']} ausente neste banco -- a coleta correspondente "
            "nao rodou. Rode inpi/ingest.py.")}

    top = max(1, min(int(top), 500))
    de_iso, ate_iso = _norm_periodo(de, fim=False), _norm_periodo(ate, fim=True)

    principal = _computar(dataset, metrica, agrupar_por, escritorio, titular, cpc,
                          de_iso, ate_iso, top)

    out: dict = {
        "dataset": dataset,
        "metrica": metrica,
        "agrupar_por": agrupar_por,
        "filtro": {"escritorio": escritorio, "titular": titular, "cpc": cpc,
                   "de": de, "ate": ate},
        "resultado": principal["resultado"],
        "total": principal["total"],
        "proximas_analises": _proximas(dataset, escritorio, comparar_com),
        "nota": (
            "Agregacao sobre os dados que a base tem. Metrica de valor descarta "
            "valor-lixo (GRU vazada) pela regra de parse_valor e o conta em "
            "descartados_invalidos; nao e valor oficial de retribuicao."
        ),
    }
    if ds["tem_valor"]:
        out["moeda"] = principal["moeda"]
        out["descartados_invalidos"] = principal["descartados_invalidos"]
        out["cobertura"] = principal["cobertura"]

    if comparar_com:
        bancas = [comparar_com] if isinstance(comparar_com, str) else list(comparar_com)
        # lado a lado: a banca principal (se houver) + as comparadas.
        alvos = ([escritorio] if escritorio else []) + bancas
        comparativo = []
        for banca in alvos:
            c = _computar(dataset, metrica, agrupar_por, banca, titular, cpc,
                          de_iso, ate_iso, top)
            item = {"escritorio": banca, "chave": c["chave"],
                    "resultado": c["resultado"], "total": c["total"]}
            if ds["tem_valor"]:
                item["cobertura"] = c["cobertura"]
                item["descartados_invalidos"] = c["descartados_invalidos"]
            comparativo.append(item)
        out["comparativo"] = comparativo

    return out
