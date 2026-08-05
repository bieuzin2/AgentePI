"""Pipeline de busca de anterioridade: executa INPI + EPO + OpenAlex em paralelo,
deduplica por familia INPADOC e devolve lista ranqueada com estrategia auditavel.

O QUE ESTE MODULO NAO FAZ: decompor a invencao em conceitos/sinonimos -- isso e
trabalho do LLM via skill analista-patentes-inpi (releia-a antes de chamar
busca_anterioridade). Este script so executa consultas ja decompostas. Tambem NAO
da veredito de patenteabilidade: a saida e informacao organizada e citavel, nunca
"esta antecipado" ou "e patenteavel".

PPUBS (USPTO, busca BRS): fora de escopo aqui -- nao ha cliente Python direto e
reusavel neste repo, so o servidor MCP `uspto` (ppubs_search_patents). TODO: quando
houver wrapper Python, integrar como quarta fonte paralela.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from busca import openalex
from inpi import familia_epo
from inpi.consulta import inpi_busca_ipc, inpi_busca_texto


def _fonte_inpi_texto(conceito: str, limite: int, desde: str | None) -> list[dict]:
    d = inpi_busca_texto(conceito, campo="ambos", limite=limite, desde=desde)
    return [
        {"fonte": "inpi:texto", "conceito": conceito, "numero_inpi": r["numero_inpi"],
         "referencia": f"BR-{r['numero_inpi']}", "titulo": r.get("titulo"),
         "data_publicacao": r.get("data_publicacao"), "data_deposito": r.get("data_deposito")}
        for r in d.get("resultados", [])
    ]


def _fonte_inpi_ipc(simbolo: str, limite: int, desde: str | None) -> list[dict]:
    d = inpi_busca_ipc(simbolo, limite=limite, desde=desde)
    return [
        {"fonte": "inpi:ipc", "conceito": simbolo, "numero_inpi": r["numero_inpi"],
         "referencia": f"BR-{r['numero_inpi']}", "titulo": r.get("titulo"),
         "data_publicacao": None, "data_deposito": r.get("data_deposito")}
        for r in d.get("resultados", [])
    ]


def _fonte_epo(conceitos: list[str], ipc: list[str] | None, limite: int) -> list[dict]:
    from epo.epo_mcp import epo_biblio, epo_busca

    partes = [f'ta="{c}"' for c in conceitos]
    cql = " or ".join(partes)
    if ipc:
        cql = f"({cql}) and ({' or '.join(f'ipc={i}' for i in ipc)})"
    busca = epo_busca(cql, inicio=1, fim=limite)
    if busca.get("erro"):
        return []
    saida = []
    for ref in busca.get("resultados", []):
        bib = epo_biblio(ref)
        docs = bib.get("documentos") or [{}]
        doc = docs[0]
        saida.append({
            "fonte": "epo:cql", "conceito": "; ".join(conceitos), "referencia": ref,
            "titulo": doc.get("titulo"), "data_publicacao": doc.get("data_publicacao"),
            "data_deposito": None,
        })
    return saida


def _fonte_openalex(conceitos: list[str], desde: str | None, limite: int) -> list[dict]:
    d = openalex.buscar(" ".join(conceitos), desde=desde, limite=limite)
    return d.get("resultados", [])


def _resolver_membros_familia(item: dict) -> set[str]:
    """Referencias da familia INPADOC de um resultado de patente, incluindo ele
    mesmo. Conjunto vazio = familia nao resolvida (sem dedup possivel para este item,
    ele fica sozinho no proprio grupo)."""
    try:
        if item["fonte"].startswith("inpi"):
            d = familia_epo.familia(item["numero_inpi"])
        elif item["fonte"].startswith("epo"):
            from epo.epo_mcp import epo_familia_inpadoc

            d = epo_familia_inpadoc(item["referencia"])
        else:
            return set()
    except Exception:
        return set()
    if d.get("erro"):
        return set()
    membros = {m["referencia"] for m in d.get("membros", []) if m.get("referencia")}
    membros.add(item["referencia"])
    return membros


def _deduplicar_por_familia(itens: list[dict]) -> list[dict]:
    """Agrupa resultados de patente (INPI + EPO) que pertencem a mesma familia
    INPADOC. Um representante por familia; os demais entram em 'tambem_em'.
    NPL (OpenAlex) nao passa por aqui -- nao tem familia de patente.
    """
    grupos: list[dict] = []  # cada grupo: {"membros_vistos": set, "itens": [...]}
    for item in itens:
        familia = _resolver_membros_familia(item)
        alvo = None
        if familia:
            for g in grupos:
                if g["membros_vistos"] & familia:
                    alvo = g
                    break
        if alvo is None:
            alvo = {"membros_vistos": set(), "itens": []}
            grupos.append(alvo)
        alvo["membros_vistos"] |= familia
        alvo["itens"].append(item)

    saida = []
    for g in grupos:
        # Ordena por data (mais antiga primeiro) para o representante ser
        # deterministico e ser a publicacao mais cedo conhecida do grupo.
        itens_g = sorted(
            g["itens"],
            key=lambda i: i.get("data_publicacao") or i.get("data_deposito") or "9999",
        )
        representante = itens_g[0]
        saida.append({
            **representante,
            "conceitos_encontrados": sorted({i["conceito"] for i in itens_g}),
            "fontes": sorted({i["fonte"] for i in itens_g}),
            "tambem_em": [
                {"fonte": i["fonte"], "referencia": i["referencia"], "conceito": i["conceito"]}
                for i in itens_g[1:]
            ],
            "familia_resolvida": bool(g["membros_vistos"]),
        })
    return saida


def busca_anterioridade(conceitos: list[str], ipc: list[str] | None = None,
                         desde: str | None = None, data_critica: str | None = None,
                         limite_por_fonte: int = 20) -> dict:
    """Executa a busca de anterioridade em paralelo (INPI + EPO OPS + OpenAlex),
    deduplica patentes por familia INPADOC e devolve lista ranqueada + estrategia.

    Args:
        conceitos: conceitos-chave ja decompostos (e com sinonimos, se houver) --
            isso e trabalho da skill analista-patentes-inpi, feito ANTES de chamar
            esta funcao. Cada string vira uma consulta de texto no INPI e entra na
            CQL do EPO e na busca do OpenAlex.
        ipc: classificacoes IPC opcionais (formato 'B65D 65/46' ou prefixo).
        desde: 'AAAA-MM-DD' opcional -- filtra resultados a partir desta data.
        data_critica: 'AAAA-MM-DD' opcional -- data de deposito/prioridade do caso em
            exame. Cada resultado ganha 'anterior_a_data_critica' (bool ou None se
            sem data), mas a funcao NAO decide patenteabilidade -- so organiza.
        limite_por_fonte: teto de resultados por consulta individual (1-50).
    """
    if not conceitos:
        return {"erro": True, "mensagem": "Informe ao menos um conceito-chave "
                "(decomposto pela skill analista-patentes-inpi)."}
    limite_por_fonte = max(1, min(limite_por_fonte, 50))

    cobertura: dict[str, Any] = {}
    brutos: list[dict] = []
    npl: list[dict] = []

    tarefas = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for c in conceitos:
            tarefas[ex.submit(_fonte_inpi_texto, c, limite_por_fonte, desde)] = "inpi:texto"
        for i in (ipc or []):
            tarefas[ex.submit(_fonte_inpi_ipc, i, limite_por_fonte, desde)] = "inpi:ipc"
        tarefas[ex.submit(_fonte_epo, conceitos, ipc, limite_por_fonte)] = "epo:cql"
        tarefas[ex.submit(_fonte_openalex, conceitos, desde, limite_por_fonte)] = "openalex"

        for fut in as_completed(tarefas):
            nome = tarefas[fut]
            try:
                resultado = fut.result()
            except Exception as e:
                cobertura[nome] = {"executou": False, "erro": str(e)[:300]}
                continue
            cobertura.setdefault(nome, {"executou": True, "hits": 0})
            cobertura[nome]["hits"] = cobertura[nome].get("hits", 0) + len(resultado)
            if nome == "openalex":
                npl.extend(resultado)
            else:
                brutos.extend(resultado)

    cobertura["ppubs"] = {
        "executou": False,
        "motivo": ("Fora de escopo desta fase: sem cliente Python direto reusavel "
                   "para PPUBS/BRS neste repo. Rode manualmente via servidor MCP "
                   "'uspto' (ppubs_search_patents). TODO: integrar quando houver "
                   "wrapper Python."),
    }

    deduplicado = _deduplicar_por_familia(brutos)

    if data_critica:
        for item in deduplicado:
            data = item.get("data_publicacao") or item.get("data_deposito")
            item["anterior_a_data_critica"] = (data < data_critica) if data else None
        for item in npl:
            data = item.get("data_publicacao")
            item["anterior_a_data_critica"] = (data < data_critica) if data else None

    deduplicado.sort(key=lambda i: (
        -len(i["conceitos_encontrados"]),
        i.get("data_publicacao") or i.get("data_deposito") or "9999",
    ))

    return {
        "conceitos": conceitos,
        "ipc": ipc or [],
        "data_critica": data_critica,
        "estrategia": {
            "fontes_executadas": cobertura,
            "familias_apos_dedup": len(deduplicado),
            "resultados_brutos_antes_do_dedup": len(brutos),
        },
        "resultados_patentes": deduplicado,
        "resultados_npl": npl,
        "aviso": (
            "Informacao organizada para triagem, NAO veredito de patenteabilidade. "
            "Dedup por familia INPADOC pode falhar silenciosamente para itens sem "
            "'familia_resolvida'=true -- confira 'estrategia.fontes_executadas' antes "
            "de tratar a cobertura como completa. PPUBS nao rodou nesta fase."
        ),
    }
