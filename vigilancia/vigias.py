"""Os 5 vigias da vigilancia autonoma (docs/plano-v2.md secao 4.1).

Cada vigia devolve uma lista de alertas -- dicts com o mesmo formato, para que
executar.py e o e-mail nao precisem saber a origem de cada um:

    {
        "tipo": "despacho_novo" | "anulacao" | "concorrente" | "ipc" |
                "anuidade" | "exterior",
        "severidade": "alta" | "media" | "baixa",
        "processo": str | None,   # numero INPI, quando aplicavel
        "titular": str | None,
        "mensagem": str,          # resumo em portugues, pronto para o e-mail
        "data": str | None,       # data do evento (RPI, publicacao, ...)
        "fonte": str,             # proveniencia -- de onde veio o dado
        "data_corte": str,        # ate quando a base usada estava atualizada
    }

Nenhum vigia inventa numero nem da veredito -- so relata o que a base/API
publicou, com fonte e data de corte (principio da ancora tripla, secao 10.6
do plano).
"""

from __future__ import annotations

from inpi import familia_epo as fam
from inpi.consulta import _RE_ANULA, inpi_busca_ipc, inpi_cobertura, inpi_portfolio_titular, normaliza_numero
from inpi.prazos import inpi_novidades, inpi_prazos_carteira

# Codigos de despacho que, combinados com o texto "Anulada a publicacao ... na
# RPI ...", indicam anulacao de um ato anterior. Caso de referencia: PI0803071,
# onde 21.8 anulou a extincao publicada em 21.6.
_CODIGOS_ANULACAO_PREFIXOS = ("8.8", "21.8", "15.")


def _e_anulacao(despacho: dict) -> bool:
    cod = str(despacho.get("codigo_despacho") or "")
    if not cod.startswith(_CODIGOS_ANULACAO_PREFIXOS):
        return False
    return bool(_RE_ANULA.search(despacho.get("complemento_despacho") or ""))


def vigia_carteira(numeros: list[str], desde: str) -> list[dict]:
    """Vigia 1: despachos novos na watchlist da carteira desde a ultima execucao.

    Marca em vermelho (severidade alta) despacho que ANULA um ato anterior --
    quem le so o despacho anulado agiria sobre algo que deixou de existir.
    """
    if not numeros:
        return []
    r = inpi_novidades(desde=desde, numeros=[normaliza_numero(n) for n in numeros])
    if r.get("erro"):
        return []
    cobertura = r["cobertura_da_base"]
    corte = str(cobertura.get("ultima_rpi"))
    alertas = []
    for d in r["resultados"]:
        anulacao = _e_anulacao(d)
        alertas.append({
            "tipo": "anulacao" if anulacao else "despacho_novo",
            "severidade": "alta" if anulacao else "media",
            "processo": d["numero_inpi"],
            "titular": None,
            "mensagem": (
                f"{'ANULACAO -- ' if anulacao else ''}Despacho {d['codigo_despacho']} "
                f"(RPI {d['numero_rpi']} de {d['data_rpi']}): "
                f"{(d.get('complemento_despacho') or '')[:280]}"
            ),
            "data": str(d["data_rpi"]),
            "fonte": "INPI Dados Abertos -- despachos",
            "data_corte": corte,
        })
    return alertas


def vigia_concorrentes(titulares: list[str], desde: str) -> list[dict]:
    """Vigia 2: novos depositos de titulares concorrentes vigiados."""
    alertas = []
    corte = str(inpi_cobertura().get("ultima_rpi"))
    for nome in titulares:
        r = inpi_portfolio_titular(nome, agrupar=True, limite=200)
        for item in r["resultados"]:
            dep = item.get("data_deposito")
            if not dep or str(dep) < desde:
                continue
            alertas.append({
                "tipo": "concorrente",
                "severidade": "baixa",
                "processo": item["numero_inpi"],
                "titular": item.get("depositante") or nome,
                "mensagem": (
                    f"Novo deposito de '{item.get('depositante') or nome}' "
                    f"em {dep}: {item.get('titulo') or '(sem titulo)'}"
                ),
                "data": str(dep),
                "fonte": "INPI Dados Abertos -- biblio/depositantes",
                "data_corte": corte,
            })
    return alertas


def vigia_ipc(ipcs: list[str], desde: str) -> list[dict]:
    """Vigia 3: novos depositos nas classificacoes IPC vigiadas."""
    alertas = []
    corte = str(inpi_cobertura().get("ultima_rpi"))
    for simbolo in ipcs:
        r = inpi_busca_ipc(simbolo, limite=100, desde=desde)
        for item in r["resultados"]:
            alertas.append({
                "tipo": "ipc",
                "severidade": "baixa",
                "processo": item["numero_inpi"],
                "titular": None,
                "mensagem": (
                    f"Novo deposito em {simbolo} ({item.get('simbolo')}) "
                    f"em {item.get('data_deposito')}: {item.get('titulo') or '(sem titulo)'}"
                ),
                "data": str(item.get("data_deposito")),
                "fonte": "INPI Dados Abertos -- classificacao IPC",
                "data_corte": corte,
            })
    return alertas


def vigia_anuidades(numeros: list[str], hoje: str, estado_anterior: dict | None = None) -> tuple[list[dict], dict]:
    """Vigia 4: anuidades entrando na janela de 90 dias (projecao art. 84).

    Diff contra o `estado_anterior` (mapa numero_inpi -> lista de anuidades em
    aberto na ultima execucao). Devolve (alertas, novo_estado) -- quem chama
    persiste o novo_estado para a proxima diferenca.
    """
    if not numeros:
        return [], {}
    estado_anterior = estado_anterior or {}
    from datetime import date, timedelta
    d_ini = date.fromisoformat(hoje)
    d_fim = d_ini + timedelta(days=90)
    r = inpi_prazos_carteira(
        numeros=[normaliza_numero(n) for n in numeros],
        de=d_ini.isoformat(), ate=d_fim.isoformat(), tipos=["anuidade"],
    )
    if r.get("erro"):
        return [], estado_anterior

    novo_estado: dict[str, list[str]] = {}
    alertas = []
    for p in r["prazos"]:
        num = p["numero_inpi"]
        novo_estado.setdefault(num, []).append(p["descricao"])
        ja_visto = p["descricao"] in estado_anterior.get(num, [])
        if not ja_visto:
            alertas.append({
                "tipo": "anuidade",
                "severidade": "media",
                "processo": num,
                "titular": None,
                "mensagem": (
                    f"{p['descricao']} entra na janela de 90 dias: prazo "
                    f"{p['prazo']} ({p['base_legal']})"
                ),
                "data": p["prazo"],
                "fonte": "Projecao inpi.anuidades (art. 84 LPI) sobre INPI Dados Abertos",
                "data_corte": hoje,
            })
    return alertas, novo_estado


def vigia_exterior(numeros: list[str], estado_anterior: dict | None = None) -> tuple[list[dict], dict]:
    """Vigia 5 (mensal, poupa quota EPO): mudanca de status legal INPADOC.

    Compara o status legal por pais de cada familia contra o `estado_anterior`
    (mapa referencia -> {pais: status resumido}). So roda quando executar.py
    decide que e a primeira execucao do mes.
    """
    if not numeros:
        return [], {}
    from epo.epo_mcp import epo_status_legal

    estado_anterior = estado_anterior or {}
    novo_estado: dict[str, dict] = {}
    alertas = []
    for numero in numeros:
        f = fam.familia(normaliza_numero(numero))
        if f.get("erro"):
            continue
        for m in f.get("membros", []):
            ref = m["referencia"]
            status = epo_status_legal(ref, apenas_nacionais=True)
            if not status.get("encontrado"):
                continue
            resumo = {
                pais: {"caducou": v["caducou"], "taxa_paga": v["taxa_paga"]}
                for pais, v in status.get("por_pais", {}).items()
            }
            novo_estado[ref] = resumo
            anterior = estado_anterior.get(ref, {})
            for pais, v in resumo.items():
                if v != anterior.get(pais):
                    alertas.append({
                        "tipo": "exterior",
                        "severidade": "media" if v["caducou"] else "baixa",
                        "processo": numero,
                        "titular": None,
                        "mensagem": (
                            f"Familia de {numero} ({ref}), pais {pais}: status legal "
                            f"mudou -- caducou={v['caducou']}, taxa_paga={v['taxa_paga']}"
                        ),
                        "data": status.get("por_pais", {}).get(pais, {}).get("ultimo_evento"),
                        "fonte": "EPO OPS -- INPADOC legal status",
                        "data_corte": None,
                    })
    return alertas, novo_estado
