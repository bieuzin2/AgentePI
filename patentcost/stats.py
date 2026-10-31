"""Estatística pública agregada por seção IPC (INPI) no formato patentcost-stats-1.

Universo: pedidos depositados no período COM decisão final publicada (16.1 concessão, 9.2 indeferimento,
11.x arquivamento) — usar só decididos evita o viés do lag de publicação (pedidos recentes ainda sem exame
puxariam a média de exigências para baixo). Exigência = despachos 6.1/2.5/7.1 (mesma definição de
inpi/mercado.py). Saída é agregada e pública: nenhum dado de cliente.
"""
from __future__ import annotations

EXIG = ("6.1", "2.5", "7.1")
DECISAO = ("16.1", "9.2", "11.1", "11.2")


def estatistica_por_secao(de: str, ate: str, con=None) -> list[dict]:
    if con is None:
        from inpi.db import con as _con
        con = _con()
    sql = f"""
    WITH base AS (
      SELECT b.numero_inpi, min(b.data_deposito) dep,
             upper(substr(any_value(i.simbolo), 1, 1)) secao
      FROM biblio b JOIN ipc i ON i.numero_inpi = b.numero_inpi AND i.ordem = 1
      WHERE b.data_deposito BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
      GROUP BY b.numero_inpi
    ), dec AS (
      SELECT numero_inpi, min(data_rpi) FILTER (WHERE codigo_despacho = '16.1') conc,
             count(*) FILTER (WHERE codigo_despacho IN {DECISAO}) ndec,
             count(*) FILTER (WHERE codigo_despacho IN {EXIG}) nexig,
             min(data_rpi) FILTER (WHERE codigo_despacho IN {EXIG}) exig1
      FROM despachos GROUP BY numero_inpi
    )
    SELECT secao, count(*) n,
           avg(CASE WHEN nexig > 0 THEN 1.0 ELSE 0.0 END) prob,
           avg(nexig) FILTER (WHERE nexig > 0) media,
           median(date_diff('day', dep, exig1)) FILTER (WHERE nexig > 0) d_exame,
           median(date_diff('day', dep, conc)) FILTER (WHERE conc IS NOT NULL) d_conc
    FROM base JOIN dec USING (numero_inpi)
    WHERE ndec > 0 AND secao BETWEEN 'A' AND 'H'
    GROUP BY secao ORDER BY secao
    """
    rows = con.execute(sql, [de, ate]).fetchall()
    out = []
    for secao, n, prob, media, d_ex, d_conc in rows:
        r = {"jurisdicao": "BR", "secao": secao, "n": int(n), "prob_exigencia": round(float(prob), 4), "media_exigencias": round(float(media or 0), 3),
             "periodo": f"{de}–{ate}", "origem": "INPI dados abertos (despachos 6.1/2.5/7.1; pedidos decididos)"}
        if d_ex is not None:
            r["meses_ate_exame"] = round(float(d_ex) / 30.44, 1)
        if d_conc is not None:
            r["meses_ate_concessao"] = round(float(d_conc) / 30.44, 1)
        out.append(r)
    return out
