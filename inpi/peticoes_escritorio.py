"""Peticoes REALMENTE protocoladas (ledger da ficha do pePI), por escritorio/periodo.

Irma de inpi_anuidades_pagas: mesma fonte (ficha do pePI, tabela ficha_peticoes),
mesma disciplina de cobertura. Existe porque o INPI so publica na RPI a EXIGENCIA
(a demanda), nunca o CUMPRIMENTO dela -- que e uma peticao (codigo 207) protocolada
pelo escritorio. Ate agora o agente era instruido a dizer "nao da pra saber quantas
exigencias foram cumpridas"; com o ledger de peticoes isso passa a ter resposta
factual, alem de qualquer outra peticao (recurso 214, transferencia 249, exame 203,
manifestacao 281, etc.).

MESMO LIMITE DE COBERTURA do ledger de anuidades: so os pedidos que a coleta raspou
(bancas alvo). Fora desse escopo o ledger vem vazio -- total 0 = "nao coletado",
nunca "nao protocolou nada". A tool declara a cobertura.
"""

from __future__ import annotations

from inpi import escritorios as esc
from inpi.anuidades_pagas import _norm_periodo
from inpi.consulta import _linhas, _tem_tabela
from inpi.mcp_app import mcp


@mcp.tool()
def inpi_peticoes_escritorio(escritorio: str, codigos: list[str] | None = None,
                             de: str | None = None, ate: str | None = None) -> dict:
    """Quantas peticoes um escritorio protocolou no pePI, por codigo e periodo.

    USE QUANDO: a pergunta for sobre ato REALMENTE protocolado -- em especial
    "quantas exigencias o escritorio X cumpriu" (cumprimento de exigencia = peticao
    codigo 207, que a RPI nao publica; inpi_exigencias_escritorio so ve a exigencia,
    nao o cumprimento). Serve tambem para recurso (214), pedido de exame (203),
    transferencia (249), manifestacao (281) e qualquer outro codigo de peticao.

    Fonte: ledger da ficha do pePI (tabela ficha_peticoes: codigo, descricao,
    data_protocolo). Conta peticao com data de protocolo no periodo.

    Args:
        escritorio: nome do escritorio (resolvido para a chave canonica).
        codigos: lista de codigos de peticao a contar (ex.: ['207'] para
            cumprimento de exigencia). None conta todas, agrupando por codigo.
        de: inicio 'AAAA-MM' ou 'AAAA-MM-DD'. Omita para sem limite.
        ate: fim 'AAAA-MM' ou 'AAAA-MM-DD'. Omita para sem limite.
    """
    if not _tem_tabela("ficha_peticoes"):
        return {"erro": True, "mensagem": (
            "Tabela ficha_peticoes ausente -- a coleta da ficha do pePI nao rodou "
            "neste banco. Rode inpi/ingest.py com o ficha-extras.csv presente.")}

    chave = esc.normalizar(escritorio)
    de_iso, ate_iso = _norm_periodo(de, fim=False), _norm_periodo(ate, fim=True)

    cond = ["dt IS NOT NULL"]
    params: list = [chave]
    if codigos:
        marcadores = ",".join("?" * len(codigos))
        cond.append(f"codigo IN ({marcadores})")
        params.extend([str(c) for c in codigos])
    if de_iso:
        cond.append("strftime(dt, '%Y-%m-%d') >= ?")
        params.append(de_iso)
    if ate_iso:
        cond.append("strftime(dt, '%Y-%m-%d') <= ?")
        params.append(ate_iso)

    linhas = _linhas(
        f"""
        WITH alvo AS (
          SELECT DISTINCT p.numero_inpi
          FROM procuradores p JOIN escritorios e ON e.original = p.procurador
          WHERE e.chave = ?
        ),
        pt AS (
          SELECT fp.codigo, fp.descricao,
                 try_strptime(fp.data_protocolo, '%d/%m/%Y') AS dt
          FROM ficha_peticoes fp JOIN alvo USING (numero_inpi)
          WHERE fp.data_protocolo IS NOT NULL AND fp.data_protocolo <> ''
        )
        SELECT codigo, any_value(descricao) AS descricao, count(*) AS n
        FROM pt WHERE {' AND '.join(cond)}
        GROUP BY codigo ORDER BY n DESC
        """,
        params,
    )

    total = sum(r["n"] for r in linhas)
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
        "filtro": {"codigos": codigos, "de": de, "ate": ate},
        "total_peticoes": total,
        "por_codigo": [
            {"codigo": r["codigo"], "descricao": r["descricao"], "quantidade": r["n"]}
            for r in linhas
        ],
        "fonte": "ledger da ficha do pePI (ficha_peticoes) -- ato protocolado",
        "cobertura": {
            "pedidos_com_ficha_coletada": cobertura,
            "aviso": (
                "So conta o que a coleta da ficha do pePI raspou (bancas alvo). "
                "Se pedidos_com_ficha_coletada for baixo/zero, a coleta NAO cobriu "
                "este escritorio -- total 0 significa 'nao coletado', NUNCA 'nao "
                "protocolou nada'. Confirme a cobertura antes de afirmar ausencia."
            ),
        },
        "nota": (
            "Cumprimento de exigencia = codigo 207 (a RPI publica a exigencia, nao o "
            "cumprimento). Peticao protocolada, distinta da exigencia vista na RPI "
            "por inpi_exigencias_escritorio."
        ),
    }
