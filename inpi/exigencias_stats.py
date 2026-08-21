"""Estatistica de EXIGENCIAS de exame por escritorio, com comparativo concorrente.

Duas metricas, ambas sobre a BASE ABERTA (despachos + biblio) -- NAO dependem da
ficha raspada do pePI, entao valem para qualquer escritorio, nao so as bancas alvo:

  1) MEDIA DE EXIGENCIAS POR PEDIDO -- quantas exigencias de exame (despachos
     6.1/2.5/7.1) um pedido do escritorio recebe, em media. Denominador HONESTO =
     TODOS os pedidos do escritorio (inclui os que receberam 0 exigencias); nao so
     os que tiveram exigencia. Vem tambem a distribuicao (0/1/2/3+ exigencias).

  2) MEDIANA DE DIAS DEPOSITO -> 1a EXIGENCIA -- para os pedidos que tiveram ao
     menos uma exigencia, mediana (e media) de dias entre biblio.data_deposito e a
     data_rpi da PRIMEIRA exigencia. E o RITMO do exame.

Ressalva conservadora do repo: exigencia e ato da FASE DE EXAME, sempre POSTERIOR
ao deposito -- por isso a unica medida temporal que faz sentido e deposito->1a
exigencia (nunca "ate o deposito"). E o dado sofre o lag de publicacao (art. 30
LPI): pedidos recentes ainda em sigilo/sem exame puxam a media para baixo por
ainda nao terem recebido exigencia, nao por qualidade -- ver aviso_lag_publicacao.

Reusa o padrao alvo/chave de inpi/anuidades_pagas.py, os codigos de exigencia de
inpi/mercado.py (_CODIGOS_EXIGENCIA) e _norm_periodo. So funcao + helpers puros --
a thread principal registra a @mcp.tool.
"""

from __future__ import annotations

from inpi import escritorios as esc
from inpi.anuidades_pagas import _norm_periodo
from inpi.consulta import _linhas
from inpi.mercado import _CODIGOS_EXIGENCIA

# Codigos que contam como "o INPI emitiu uma exigencia de exame" (6.1/2.5/7.1).
# Importados de mercado.py para nao divergir da definicao ja usada no projeto.
_COD_EXIG = tuple(_CODIGOS_EXIGENCIA)


def _metricas(chave: str | None, cpc: str | None,
              de_iso: str | None, ate_iso: str | None) -> dict:
    """Roda as duas metricas para um conjunto de pedidos.

    chave=None => BASE INTEIRA (todos os pedidos, sem filtro de escritorio),
    usada como baseline no comparativo. chave!=None => pedidos do escritorio via
    join procuradores->escritorios (padrao de anuidades_pagas.py).
    """
    # 'pedidos' = universo do escritorio (ou base inteira), ancorado em biblio para
    # ter data_deposito e aplicar os filtros de cpc/periodo. O DISTINCT importa: um
    # pedido tem varias linhas de procurador/ipc e nao pode contar em dobro.
    params: list = []
    alvo_cte = ""
    join_alvo = ""
    if chave is not None:
        alvo_cte = (
            "alvo AS (SELECT DISTINCT p.numero_inpi FROM procuradores p "
            "JOIN escritorios e ON e.original = p.procurador WHERE e.chave = ?), "
        )
        join_alvo = "JOIN alvo a ON a.numero_inpi = b.numero_inpi"
        params.append(chave)

    cond = []
    if cpc:
        cond.append("EXISTS (SELECT 1 FROM ipc i WHERE i.numero_inpi = b.numero_inpi "
                    "AND i.simbolo LIKE ?)")
        params.append(cpc.strip() + "%")
    if de_iso:
        cond.append("b.data_deposito >= ?")
        params.append(de_iso)
    if ate_iso:
        cond.append("b.data_deposito <= ?")
        params.append(ate_iso)
    where = ("WHERE " + " AND ".join(cond)) if cond else ""

    placeholders = ",".join("?" for _ in _COD_EXIG)
    params.extend(_COD_EXIG)

    sql = f"""
        WITH {alvo_cte}pedidos AS (
          SELECT DISTINCT b.numero_inpi, b.data_deposito
          FROM biblio b {join_alvo} {where}
        ),
        exig AS (
          SELECT numero_inpi, count(*) AS n, min(data_rpi) AS primeira
          FROM despachos WHERE codigo_despacho IN ({placeholders})
          GROUP BY numero_inpi
        ),
        per AS (
          SELECT coalesce(e.n, 0) AS n_exig,
                 CASE WHEN e.n > 0 AND p.data_deposito IS NOT NULL
                      THEN datediff('day', p.data_deposito, e.primeira) END AS dias
          FROM pedidos p LEFT JOIN exig e USING (numero_inpi)
        )
        SELECT count(*) AS pedidos,
               coalesce(sum(n_exig), 0) AS total_exig,
               count(*) FILTER (WHERE n_exig = 0) AS b0,
               count(*) FILTER (WHERE n_exig = 1) AS b1,
               count(*) FILTER (WHERE n_exig = 2) AS b2,
               count(*) FILTER (WHERE n_exig >= 3) AS b3,
               count(*) FILTER (WHERE n_exig > 0) AS com_exig,
               count(dias) AS com_dias,
               median(dias) AS med, avg(dias) AS media
        FROM per
    """
    r = _linhas(sql, params)[0]

    pedidos = r["pedidos"] or 0
    media_exig = round(r["total_exig"] / pedidos, 3) if pedidos else 0.0
    return {
        "pedidos": pedidos,
        "media_exigencias_por_pedido": media_exig,
        "distribuicao_exigencias": {
            "0": r["b0"] or 0, "1": r["b1"] or 0,
            "2": r["b2"] or 0, "3+": r["b3"] or 0,
        },
        "dias_ate_primeira_exigencia": {
            # mediana/media so sobre pedidos com exigencia E com data_deposito
            # (com_dias); com_exig e a contagem honesta de quem teve exigencia.
            "mediana": round(r["med"]) if r["med"] is not None else None,
            "media": round(r["media"]) if r["media"] is not None else None,
            "pedidos_com_exigencia": r["com_exig"] or 0,
        },
    }


def inpi_exigencias_stats(escritorio: str, cpc: str | None = None,
                          comparar_com: str | list[str] | None = None,
                          de: str | None = None, ate: str | None = None) -> dict:
    """Ritmo e volume de EXIGENCIAS de exame de um escritorio, com comparativo.

    USE QUANDO: a pergunta for "quantas exigencias os pedidos da banca X pegam, em
    media?" ou "quao rapido o INPI examina os pedidos dela?" -- e para comparar isso
    com um concorrente ou com o mercado. Duas metricas: (1) media de exigencias por
    pedido (denominador = TODOS os pedidos, inclui os com 0 -- media honesta) mais a
    distribuicao 0/1/2/3+; (2) mediana de dias do deposito ate a 1a exigencia (ritmo
    do exame), so sobre os pedidos que tiveram exigencia.

    Diferente de inpi_exigencias_escritorio (que conta emitidas x desfecho num ANO):
    aqui a unidade e o PEDIDO ao longo de toda a vida dele, e a saida e uma media/mediana.

    Base aberta (despachos 6.1/2.5/7.1 + biblio) -- NAO depende da ficha raspada,
    entao vale para qualquer escritorio. Exigencia e da FASE DE EXAME, posterior ao
    deposito: por isso so medimos deposito->1a exigencia (nao "ate o deposito"). O
    dado sofre lag de publicacao (art. 30 LPI): pedidos recentes ainda sem exame
    baixam a media por ainda nao terem recebido exigencia, nao por merito.

    Args:
        escritorio: nome do escritorio (resolvido para a chave canonica curada).
        cpc: opcional, prefixo de classificacao (join ipc.simbolo LIKE prefixo%),
            ex.: 'A61' restringe a quimica/farma.
        comparar_com: opcional, banca concorrente (str) ou lista de bancas. Roda as
            MESMAS metricas para cada uma e para a BASE INTEIRA (baseline de mercado)
            e devolve lado a lado em 'comparativo'.
        de/ate: opcional, recorte por data_deposito do pedido, 'AAAA-MM' ou
            'AAAA-MM-DD'.
    """
    chave = esc.normalizar(escritorio)
    de_iso, ate_iso = _norm_periodo(de, fim=False), _norm_periodo(ate, fim=True)

    base = _metricas(chave, cpc, de_iso, ate_iso)

    saida: dict = {
        "escritorio": escritorio,
        "chave": chave,
        "filtro": {"cpc": cpc, "de": de, "ate": ate},
        "pedidos_considerados": base["pedidos"],
        "media_exigencias_por_pedido": base["media_exigencias_por_pedido"],
        "distribuicao_exigencias": base["distribuicao_exigencias"],
        "dias_ate_primeira_exigencia": base["dias_ate_primeira_exigencia"],
    }

    if not base["pedidos"]:
        saida["mensagem"] = (
            f"Nenhum pedido encontrado para '{escritorio}' (chave '{chave}') com esse "
            "criterio. Confira a chave em inpi_escritorio_resolver e, se usou cpc/de/ate, "
            "afrouxe o filtro. Metricas devolvidas como zero/None -- ausencia de dado, "
            "nao 'zero exigencias'.")

    if comparar_com:
        nomes = [comparar_com] if isinstance(comparar_com, str) else list(comparar_com)
        comp = [{
            "escritorio": escritorio, "chave": chave,
            "media_exigencias_por_pedido": base["media_exigencias_por_pedido"],
            "dias_mediana": base["dias_ate_primeira_exigencia"]["mediana"],
            "pedidos": base["pedidos"],
        }]
        for nome in nomes:
            ck = esc.normalizar(nome)
            m = _metricas(ck, cpc, de_iso, ate_iso)
            comp.append({
                "escritorio": nome, "chave": ck,
                "media_exigencias_por_pedido": m["media_exigencias_por_pedido"],
                "dias_mediana": m["dias_ate_primeira_exigencia"]["mediana"],
                "pedidos": m["pedidos"],
            })
        # BASE INTEIRA como baseline de mercado (mesmo cpc/periodo, sem escritorio).
        mb = _metricas(None, cpc, de_iso, ate_iso)
        comp.append({
            "escritorio": "BASE INTEIRA (mercado)", "chave": None,
            "media_exigencias_por_pedido": mb["media_exigencias_por_pedido"],
            "dias_mediana": mb["dias_ate_primeira_exigencia"]["mediana"],
            "pedidos": mb["pedidos"],
        })
        saida["comparativo"] = comp

    saida["proximas_analises"] = [
        "comparar com uma banca concorrente ou com o mercado (parametro comparar_com)",
        "recortar por tecnologia (parametro cpc, ex. 'A61') ou por periodo (de/ate)",
        "emitidas x desfecho num ano especifico: inpi_exigencias_escritorio",
        "peticoes protocoladas, incl. cumprimento de exigencia cod. 207: "
        "inpi_peticoes_escritorio",
        "anuidades realmente pagas dessa carteira: inpi_anuidades_pagas",
    ]
    saida["nota"] = (
        "Base ABERTA (despachos 6.1/2.5/7.1 + biblio), nao a ficha raspada -- vale "
        "para qualquer escritorio. media_exigencias_por_pedido usa como denominador "
        "TODOS os pedidos do escritorio (inclui os com 0 exigencias): e a media por "
        "pedido, nao por pedido-com-exigencia. dias_ate_primeira_exigencia so olha "
        "quem teve exigencia e tem data_deposito. Exigencia e da fase de EXAME "
        "(posterior ao deposito) e sofre lag de publicacao (art. 30 LPI): pedidos "
        "recentes ainda sem exame baixam a media por ainda nao terem exigencia, nao "
        "por merito -- cuidado ao comparar recortes com muitos depositos recentes."
    )
    return saida
