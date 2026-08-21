"""Anuidades REALMENTE PAGAS (ledger raspado do pePI), por escritorio e periodo.

Contraparte factual da projecao: inpi_anuidades/inpi_prazos_carteira CALCULAM o
que deveria ser pago pelo art. 84 da LPI; esta tool conta o que a ficha do pePI
registra como PAGO (tabela ficha_anuidades, com data_pagamento e GRU). Existe
porque a pergunta "quantas anuidades a Clarke pagou em marco/2025" nao tinha
resposta antes -- so havia a projecao, que o proprio agente avisava nao ser
pagamento confirmado.

LIMITE DE COBERTURA (honesto): ficha_anuidades so existe para os pedidos que a
coleta raspou (inpi/coleta_ficha_extras.py) -- na pratica as bancas alvo
(Clarke + top concorrentes). Para um escritorio fora desse escopo o ledger vem
vazio, e isso NAO significa "pagou zero": significa "nao coletado". A tool
declara a cobertura para o agente nunca ler ausencia de dado como ausencia de
pagamento.
"""

from __future__ import annotations

from inpi import escritorios as esc
from inpi.consulta import _linhas, _tem_tabela
from inpi.mcp_app import mcp
from inpi.valores import MOEDA, TETO_SANO


def _norm_periodo(p: str | None, fim: bool) -> str | None:
    """'2025-03' -> '2025-03-01' (inicio) ou '2025-03-31' (fim). 'AAAA-MM-DD'
    passa direto. None -> None (sem limite). Compara-se lexicograficamente contra
    a data ISO derivada de data_pagamento."""
    if not p:
        return None
    p = p.strip()
    if len(p) == 7:  # AAAA-MM
        return p + ("-31" if fim else "-01")
    return p


@mcp.tool()
def inpi_anuidades_pagas(escritorio: str, de: str | None = None,
                         ate: str | None = None) -> dict:
    """Quantas anuidades foram REALMENTE PAGAS por um escritorio num periodo.

    USE QUANDO: a pergunta for sobre anuidade PAGA/quitada/recolhida (nao sobre
    projecao/vencimento). Ex.: "quantas anuidades a Clarke pagou em marco de 2025".
    Para o que DEVERIA ser pago (projecao art. 84), use inpi_anuidades ou
    inpi_prazos_carteira -- sao coisas diferentes; nao troque uma pela outra.

    Fonte: ledger da ficha do pePI (tabela ficha_anuidades: data_pagamento + GRU).
    So conta linha com data de pagamento preenchida = efetivamente paga.

    Args:
        escritorio: nome do escritorio (resolvido para a chave canonica).
        de: inicio do periodo, 'AAAA-MM' ou 'AAAA-MM-DD'. Omita para sem limite.
        ate: fim do periodo, 'AAAA-MM' ou 'AAAA-MM-DD'. Omita para sem limite.
    """
    if not _tem_tabela("ficha_anuidades"):
        return {"erro": True, "mensagem": (
            "Tabela ficha_anuidades ausente -- a coleta da ficha do pePI nao rodou "
            "neste banco. Rode inpi/ingest.py com o ficha-extras.csv presente.")}

    chave = esc.normalizar(escritorio)
    de_iso, ate_iso = _norm_periodo(de, fim=False), _norm_periodo(ate, fim=True)

    # data_pagamento vem 'DD/MM/AAAA' -> converte a ISO para comparar/agrupar.
    # try_strptime devolve NULL em formato invalido (nao derruba a query). dt vem
    # do CTE 'pagas'; so o filtro por dt fica no outer query.
    cond = ["dt IS NOT NULL"]
    cond_params: list = []
    if de_iso:
        cond.append("strftime(dt, '%Y-%m-%d') >= ?")
        cond_params.append(de_iso)
    if ate_iso:
        cond.append("strftime(dt, '%Y-%m-%d') <= ?")
        cond_params.append(ate_iso)

    # Ordem dos ? no texto SQL: chave (alvo) -> os dois TETO do SELECT -> filtros do
    # WHERE. Soma de valor no proprio SQL, replicando a regra de inpi/valores:
    # tira '$' e ',', TRY_CAST, e so soma o que fica em [0, TETO_SANO] -- acima e
    # numero de GRU vazado no campo (ver inpi/valores.py). 'invalidos' conta so o
    # valor PREENCHIDO mas impossivel de parsear/acima do teto, nao o valor ausente.
    params: list = [chave, TETO_SANO, TETO_SANO, *cond_params]
    linhas = _linhas(
        f"""
        WITH alvo AS (
          SELECT DISTINCT p.numero_inpi
          FROM procuradores p JOIN escritorios e ON e.original = p.procurador
          WHERE e.chave = ?
        ),
        pagas AS (
          SELECT fa.numero_inpi,
                 try_strptime(fa.data_pagamento, '%d/%m/%Y') AS dt,
                 nullif(fa.valor, '') AS valor_bruto,
                 TRY_CAST(replace(replace(fa.valor, '$', ''), ',', '') AS DOUBLE) AS v
          FROM ficha_anuidades fa JOIN alvo USING (numero_inpi)
          WHERE fa.data_pagamento IS NOT NULL AND fa.data_pagamento <> ''
        )
        SELECT strftime(dt, '%Y-%m') AS mes,
               count(*) AS pagas,
               round(sum(CASE WHEN v >= 0 AND v <= ? THEN v ELSE 0 END), 2) AS valor,
               count(*) FILTER (
                 WHERE valor_bruto IS NOT NULL AND (v IS NULL OR v < 0 OR v > ?)
               ) AS invalidos
        FROM pagas WHERE {' AND '.join(cond)}
        GROUP BY 1 ORDER BY 1
        """,
        params,
    )

    total = sum(r["pagas"] for r in linhas)
    valor_total = round(sum(r["valor"] or 0 for r in linhas), 2)
    invalidos = sum(r["invalidos"] for r in linhas)

    # Cobertura: quantos pedidos deste escritorio a coleta cobriu. Zero = nao
    # coletado -> o total 0 nao pode ser lido como "pagou zero".
    cobertura = _linhas(
        """SELECT count(*) AS pedidos_com_ficha
           FROM ficha_extras fe
           WHERE fe.numero_inpi IN (
             SELECT DISTINCT p.numero_inpi FROM procuradores p
             JOIN escritorios e ON e.original = p.procurador WHERE e.chave = ?)""",
        [chave],
    )[0]["pedidos_com_ficha"]

    return {
        "escritorio": escritorio,
        "chave": chave,
        "periodo": {"de": de, "ate": ate},
        "total_anuidades_pagas": total,
        "valor_total_reais": valor_total,
        "valor_medio_reais": round(valor_total / total, 2) if total else 0,
        "moeda": MOEDA,
        "valores_invalidos_descartados": invalidos,
        "por_mes": {
            r["mes"]: {"pagas": r["pagas"], "valor_reais": r["valor"] or 0}
            for r in linhas
        },
        "fonte": "ledger da ficha do pePI (ficha_anuidades) -- pagamento confirmado",
        "cobertura": {
            "pedidos_com_ficha_coletada": cobertura,
            "aviso": (
                "So conta o que a coleta da ficha do pePI raspou (bancas alvo). "
                "Se pedidos_com_ficha_coletada for baixo/zero para este escritorio, "
                "a coleta NAO o cobriu -- total 0 significa 'nao coletado', NUNCA "
                "'pagou zero'. Confirme a cobertura antes de afirmar ausencia."
            ),
        },
        "proximas_analises": [
            "Estimativa de anuidades a vencer nos proximos meses: financeiro_projecao.",
            "Comparar este gasto com um concorrente: inpi_estatistica dataset="
            "'anuidades_pagas', metrica='soma_valor', comparar_com='<banca>'.",
            "Media/estatistica por CPC ou por mes: inpi_estatistica.",
        ],
        "nota": (
            "Anuidade PAGA (realizado), distinta da projecao do art. 84 "
            "(inpi_anuidades/inpi_prazos_carteira). 'valor_total_reais' soma o valor "
            "da ficha ja descartando lixo (GRU vazada); veja 'moeda' e "
            "'valores_invalidos_descartados'."
        ),
    }
