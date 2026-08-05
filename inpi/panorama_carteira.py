"""Panorama gerencial de uma carteira de escritorio: agregacao + inteligencia.

NAO e so extracao. Cada secao planeja o insight, calcula (taxas, tempos,
concentracao, coortes, risco) e devolve um dict JSON-serializavel que o render
HTML consome direto. Uma funcao publica: panorama(procurador=...).

Reusa a maquinaria ja testada do servidor:
  - _carregar_lote  -> estado de toda a carteira em 2 queries (deposito, encerrado,
                       despachos, anuidades em aberto), pela CHAVE normalizada.
  - _prazos_de      -> projeta prazos por caso (art. 33/40/84/212).
  - anu.projetar    -> anuidade (art. 84), ja calibrada contra 285 mil despachos.

O resto e agregacao SQL direta sobre inpi.duckdb -- validada contra o total
canonico da carteira (ver _valida.py). Colunas conferidas no banco real:
  biblio(numero_inpi, data_deposito, data_publicacao, numero_pct)  -- SEM data_concessao
  despachos(numero_inpi, data_rpi, codigo_despacho, complemento_despacho)
  prioridades(numero_inpi, pais_prioridade)  ipc(numero_inpi, simbolo)
Concessao = despacho 9.1 (carta-patente), nao coluna.

VERACIDADE (nao negociavel):
  - "anuidade paga" nao existe na base. So NOTIFICADA (consequencia, nao quitacao).
  - Prazo e PROJECAO, nao fatura.
  - Situacao usa os mesmos codigos terminais/reversao de anuidades.py.
"""

from __future__ import annotations

from datetime import date

from inpi import anuidades as anu
from inpi import escritorios as esc
from inpi.consulta import inpi_cobertura
from inpi.db import con
from inpi.prazos import _carregar_lote, _prazos_de

# Situacao da carteira, derivada do estado ja computado por _estado_de. Buckets
# mutuamente exclusivos, na ordem de precedencia. 9.1 = carta-patente (concedida).
_TERMINAIS_CONCESSAO = {"9.1", "16.1"}


def _classifica(est: dict) -> str:
    """Um caso -> um bucket de situacao. Usa o estado ja computado (sem tocar o banco)."""
    vivos = [d for d in est["despachos"] if not d.get("anulado_em")]
    cods = {str(d.get("codigo_despacho")) for d in vivos}
    concedida = bool(cods & _TERMINAIS_CONCESSAO)
    if est["encerrado_em"]:
        # encerrado: distingue indeferimento de arquivamento/extincao pelo terminal
        t = str((est.get("despacho_terminal") or {}).get("codigo_despacho") or "")
        if t == "9.2":
            return "indeferida"
        if t.startswith("24.") or t in ("21.6",):
            return "extinta"
        return "arquivada"  # 11.x, 8.6
    if concedida:
        return "concedida_vigente"
    return "em_andamento"


def _con():
    return con()


def _agg_por_ano_deposito(chave: str) -> list[dict]:
    r = _con().execute(
        """WITH alvo AS (SELECT DISTINCT p.numero_inpi FROM procuradores p
             JOIN escritorios e ON e.original = p.procurador WHERE e.chave = ?)
           SELECT year(b.data_deposito) ano, count(DISTINCT b.numero_inpi) n
           FROM alvo JOIN biblio b USING (numero_inpi)
           WHERE b.data_deposito IS NOT NULL
           GROUP BY 1 ORDER BY 1""",
        [chave],
    ).fetchall()
    return [{"ano": int(a), "n": n} for a, n in r if a]


def _agg_concessao(chave: str) -> dict:
    """Concedidas (9.1) e tempo deposito->concessao. Mediana + histograma por anos."""
    con = _con()
    total, conc, mediana = con.execute(
        """WITH alvo AS (SELECT DISTINCT p.numero_inpi FROM procuradores p
             JOIN escritorios e ON e.original = p.procurador WHERE e.chave = ?),
           c AS (SELECT d.numero_inpi, min(d.data_rpi) dt FROM despachos d
                 JOIN alvo USING (numero_inpi) WHERE d.codigo_despacho='9.1' GROUP BY 1)
           SELECT (SELECT count(*) FROM alvo),
                  count(*),
                  median(datediff('day', b.data_deposito, c.dt))/365.25
           FROM c JOIN biblio b USING (numero_inpi)
           WHERE b.data_deposito IS NOT NULL AND c.dt > b.data_deposito""",
        [chave],
    ).fetchone()
    hist = con.execute(
        """WITH alvo AS (SELECT DISTINCT p.numero_inpi FROM procuradores p
             JOIN escritorios e ON e.original = p.procurador WHERE e.chave = ?),
           c AS (SELECT d.numero_inpi, min(d.data_rpi) dt FROM despachos d
                 JOIN alvo USING (numero_inpi) WHERE d.codigo_despacho='9.1' GROUP BY 1)
           SELECT least(floor(datediff('day', b.data_deposito, c.dt)/365.25), 15) faixa,
                  count(*) n
           FROM c JOIN biblio b USING (numero_inpi)
           WHERE b.data_deposito IS NOT NULL AND c.dt > b.data_deposito
           GROUP BY 1 ORDER BY 1""",
        [chave],
    ).fetchall()
    return {
        "total_carteira": total,
        "concedidas": conc,
        "taxa_concessao": round(conc / total, 4) if total else None,
        "anos_ate_concessao_mediana": round(mediana, 1) if mediana else None,
        "histograma_anos": [{"anos": int(f), "n": n} for f, n in hist],
    }


def _agg_pais_prioridade(chave: str, top: int = 12) -> list[dict]:
    r = _con().execute(
        """WITH alvo AS (SELECT DISTINCT p.numero_inpi FROM procuradores p
             JOIN escritorios e ON e.original = p.procurador WHERE e.chave = ?)
           SELECT pr.pais_prioridade pais, count(DISTINCT pr.numero_inpi) n
           FROM prioridades pr JOIN alvo USING (numero_inpi)
           WHERE pr.pais_prioridade IS NOT NULL AND trim(pr.pais_prioridade) <> ''
           GROUP BY 1 ORDER BY n DESC LIMIT ?""",
        [chave, top],
    ).fetchall()
    return [{"pais": p, "n": n} for p, n in r]


# Secoes IPC (nivel 1): a letra e a area tecnica. Rotulos oficiais WIPO.
_SECOES_IPC = {
    "A": "Necessidades humanas", "B": "Operacoes/transporte", "C": "Quimica/metalurgia",
    "D": "Texteis/papel", "E": "Construcoes fixas", "F": "Mecanica/iluminacao",
    "G": "Fisica", "H": "Eletricidade",
}


def _agg_ipc(chave: str) -> list[dict]:
    r = _con().execute(
        """WITH alvo AS (SELECT DISTINCT p.numero_inpi FROM procuradores p
             JOIN escritorios e ON e.original = p.procurador WHERE e.chave = ?)
           SELECT substr(i.simbolo,1,1) sec, count(DISTINCT i.numero_inpi) n
           FROM ipc i JOIN alvo USING (numero_inpi)
           WHERE i.simbolo IS NOT NULL AND i.simbolo <> ''
           GROUP BY 1 ORDER BY n DESC""",
        [chave],
    ).fetchall()
    return [{"secao": s, "rotulo": _SECOES_IPC.get(s, s), "n": n}
            for s, n in r if s and s.isalpha()]


def _agg_clientes(chave: str, top: int = 15) -> dict:
    """Top clientes + concentracao (Pareto). Titular pela chave canonica de titular."""
    con = _con()
    linhas = con.execute(
        """WITH alvo AS (SELECT DISTINCT p.numero_inpi FROM procuradores p
             JOIN escritorios e ON e.original = p.procurador WHERE e.chave = ?),
           casos AS (
             SELECT dp.numero_inpi, arg_max(t.chave, 1) cli
             FROM depositantes dp JOIN alvo USING (numero_inpi)
             LEFT JOIN titulares t ON t.original = dp.depositante
             GROUP BY 1)
           SELECT coalesce(cli,'(sem titular)') cliente, count(*) n
           FROM casos GROUP BY 1 ORDER BY n DESC""",
        [chave],
    ).fetchall()
    total = sum(n for _, n in linhas)
    acc, pareto = 0, None
    for i, (_, n) in enumerate(linhas, 1):
        acc += n
        if pareto is None and acc >= total * 0.5:
            pareto = i  # quantos clientes = 50% da carteira
    top10 = sum(n for _, n in linhas[:10])
    return {
        "total_clientes": len(linhas),
        "top": [{"cliente": c, "n": n} for c, n in linhas[:top]],
        "concentracao_top10_pct": round(top10 / total, 4) if total else None,
        "clientes_ate_metade_da_carteira": pareto,
    }


def _agg_anuidades_notificadas(chave: str) -> list[dict]:
    """Anuidades NOTIFICADAS por ano. Nao e 'paga' -- e despacho publicado (consequencia).

    So a familia 21.x (anuidade de patente concedida), que e inequivoca. O 8.x foi
    descartado: mistura despachos que nao sao anuidade e inflaria a serie.
    """
    r = _con().execute(
        """WITH alvo AS (SELECT DISTINCT p.numero_inpi FROM procuradores p
             JOIN escritorios e ON e.original = p.procurador WHERE e.chave = ?)
           SELECT year(d.data_rpi) ano, count(*) n
           FROM despachos d JOIN alvo USING (numero_inpi)
           WHERE d.codigo_despacho LIKE '21.%'
           GROUP BY 1 ORDER BY 1""",
        [chave],
    ).fetchall()
    return [{"ano": int(a), "n": n} for a, n in r if a]


# Enum de situacao: o cliente refiltra por indice, nao por string repetida 44 mil vezes.
_SIT = ["em_andamento", "concedida_vigente", "indeferida", "arquivada", "extinta"]


def _dimensoes_lote(chave: str) -> dict[str, tuple]:
    """Uma query: por caso, a secao IPC primaria, o pais de prioridade e o cliente.

    Primaria = menor 'ordem' (IPC) / menor data (prioridade). arg_min resolve as duas
    sem subquery por caso. Cliente pela chave canonica de titular.
    """
    r = _con().execute(
        """WITH alvo AS (SELECT DISTINCT p.numero_inpi FROM procuradores p
             JOIN escritorios e ON e.original = p.procurador WHERE e.chave = ?),
           ip AS (SELECT numero_inpi, arg_min(substr(simbolo,1,1), ordem) sec
                  FROM ipc WHERE simbolo IS NOT NULL AND simbolo<>''
                  GROUP BY 1),
           pr AS (SELECT numero_inpi, arg_min(pais_prioridade, data_prioridade) pais
                  FROM prioridades WHERE pais_prioridade IS NOT NULL
                  AND trim(pais_prioridade)<>'' GROUP BY 1),
           cl AS (SELECT dp.numero_inpi, arg_max(t.chave, 1) cli
                  FROM depositantes dp LEFT JOIN titulares t ON t.original=dp.depositante
                  GROUP BY 1)
           SELECT a.numero_inpi, ip.sec, pr.pais, cl.cli
           FROM alvo a
           LEFT JOIN ip USING (numero_inpi)
           LEFT JOIN pr USING (numero_inpi)
           LEFT JOIN cl USING (numero_inpi)""",
        [chave],
    ).fetchall()
    return {row[0]: (row[1], row[2], row[3]) for row in r}


def panorama(procurador: str = "Clarke Modet", hoje: str | None = None) -> dict:
    """Panorama completo da carteira. Uma chamada, um dict pronto para o render.

    Um unico passo pela carteira produz, com as MESMAS dimensoes por caso (situacao,
    IPC, pais, cliente, ano de deposito): a fact table para segmentacao client-side, a
    coorte de vigencia e os prazos projetados. Cada prazo carrega os indices de dimensao
    do seu caso -- e o que faz a segmentacao global refiltrar tambem os prazos.
    """
    chave = esc.normalizar(procurador)
    ref = date.fromisoformat(hoje) if hoje else date.today()
    limite_12m = anu._mais_meses(ref, 12).isoformat()

    estados, total = _carregar_lote(procurador=procurador)  # 2 queries, testado
    dim = _dimensoes_lote(chave)  # secao IPC, pais, cliente por caso -- uma query

    clientes: list[str] = []
    idx_cli: dict[str, int] = {}

    def _idx_cliente(cli: str | None) -> int:
        cli = cli or "(sem titular)"
        if cli not in idx_cli:
            idx_cli[cli] = len(clientes)
            clientes.append(cli)
        return idx_cli[cli]

    situacao: dict[str, int] = {}
    vigencia_por_ano: dict[int, int] = {}
    fatos: list[list] = []
    prazos: list[dict] = []
    sem_deposito = 0

    for est in estados.values():
        num, dep = est["numero_inpi"], est["data_deposito"]
        sit = _classifica(est)
        situacao[sit] = situacao.get(sit, 0) + 1
        sec, pais, cli = dim.get(num, (None, None, None))
        # dimensoes compartilhadas: fact row E cada prazo deste caso as carregam.
        d_sit, d_ipc, d_pais, d_cli = _SIT.index(sit), sec, pais, _idx_cliente(cli)
        d_ano = dep.year if dep else None

        vivos = [x for x in est["despachos"] if not x.get("anulado_em")]
        conc = [x for x in vivos if str(x.get("codigo_despacho")) == "9.1"]
        ano_conc = min(x["data_rpi"] for x in conc).year if conc else None
        fim_vig = None
        if dep and not est["encerrado_em"]:
            f = anu.fim_vigencia(dep, num)
            if f >= ref:
                fim_vig = f.year
                vigencia_por_ano[f.year] = vigencia_por_ano.get(f.year, 0) + 1
        fatos.append([d_ano, d_sit, d_ipc, d_pais, d_cli,
                      1 if conc else 0, ano_conc, fim_vig])

        if not dep:
            sem_deposito += 1
            continue
        # Prazos 12m, enxutos para a tabela + com os indices de dimensao para refiltrar.
        for p in _prazos_de(est, ref, {"anuidade", "exame", "recurso", "vigencia"}):
            pz = p.get("prazo")
            if pz and ref.isoformat() <= pz <= limite_12m:
                prazos.append({
                    "tipo": p["tipo"], "numero_inpi": num,
                    "cliente": clientes[d_cli],  # nome normalizado (chave canonica de titular)
                    "descricao": p["descricao"], "prazo": pz, "status": p["status"],
                    "fatal": bool(p.get("alerta")) and p["tipo"] in ("exame", "recurso"),
                    "dim": [d_sit, d_ipc, d_pais, d_cli, d_ano],  # sit,ipc,pais,cli,ano
                })

    por_tipo: dict[str, int] = {}
    complementar = 0
    for p in prazos:
        por_tipo[p["tipo"]] = por_tipo.get(p["tipo"], 0) + 1
        if p.get("status") == "prazo_complementar_corrente":
            complementar += 1
    exame_fatal = sum(1 for p in prazos if p["tipo"] == "exame"
                      and p["prazo"] <= anu._mais_meses(ref, 3).isoformat())

    return {
        "escritorio": procurador,
        "chave": chave,
        "referencia": ref.isoformat(),
        "cobertura": inpi_cobertura(),
        "total_casos": total,
        "sem_data_deposito": sem_deposito,
        "situacao": situacao,
        "depositos_por_ano": _agg_por_ano_deposito(chave),
        "concessao": _agg_concessao(chave),
        "pais_prioridade": _agg_pais_prioridade(chave),
        "ipc": _agg_ipc(chave),
        "clientes": _agg_clientes(chave),
        "anuidades_notificadas": _agg_anuidades_notificadas(chave),
        "coorte_vigencia": [{"ano": a, "n": n}
                            for a, n in sorted(vigencia_por_ano.items())],
        "fatos": {"colunas": ["anoDep", "sit", "ipc", "pais", "cli", "conc",
                              "anoConc", "anoFimVig"],
                  "situacoes": _SIT, "clientes": clientes, "linhas": fatos},
        "prazos_12m": {
            "total": len(prazos),
            "por_tipo": por_tipo,
            "anuidade_prazo_complementar": complementar,
            "exame_fatal_90d": exame_fatal,
            "lista": prazos,
        },
        "avisos": {
            "anuidade": "Anuidade NOTIFICADA, nao paga. A base registra consequencia; "
                        "pagamento em dia nao gera despacho.",
            "prazo": anu.__doc__ and "PROJECAO calculada, nao fatura. Lista de conferencia "
                     "contra o docketing, nunca substituto.",
            "identidade": "Carteira pela chave normalizada. O ranking de mercado subestima "
                          "concorrentes com nome comprido -- numeros de terceiros sao piso.",
        },
    }


def demo() -> None:
    """Self-check: buckets somam o total, nenhuma secao estoura a carteira."""
    d = panorama("Clarke Modet", hoje="2026-08-04")
    tot = d["total_casos"]
    assert sum(d["situacao"].values()) == tot, (sum(d["situacao"].values()), tot)
    assert d["concessao"]["concedidas"] <= tot
    assert sum(x["n"] for x in d["depositos_por_ano"]) <= tot
    assert d["clientes"]["concentracao_top10_pct"] <= 1.0
    assert len(d["fatos"]["linhas"]) == tot, (len(d["fatos"]["linhas"]), tot)
    print(f"OK  total={tot:,}  situacao={d['situacao']}")
    print(f"    fatos={len(d['fatos']['linhas']):,} linhas, "
          f"{len(d['fatos']['clientes']):,} clientes distintos")
    print(f"    concedidas={d['concessao']['concedidas']:,} "
          f"({d['concessao']['taxa_concessao']:.1%}), "
          f"mediana={d['concessao']['anos_ate_concessao_mediana']} anos")
    print(f"    prazos 12m={d['prazos_12m']['total']:,} "
          f"exame_fatal_90d={d['prazos_12m']['exame_fatal_90d']}")


if __name__ == "__main__":
    demo()
