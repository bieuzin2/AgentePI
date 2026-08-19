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
        # NAO engolir: devolver [] aqui fazia a perna EPO aparecer como
        # 'executou: true, hits: 0' -- indistinguivel de "buscou e nao achou". Levantar
        # para o orquestrador registrar 'executou: false, erro: <motivo>' na cobertura.
        raise RuntimeError(f"EPO recusou a busca: {busca.get('mensagem') or busca}")
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


def _resumo_executivo(patentes: list[dict], npl: list[dict]) -> dict:
    """Sintese executiva DETERMINISTICA sobre o resultado ja coletado -- sem chamada
    extra a fonte alguma. Agrega so o que o pipeline realmente tem em maos (fonte,
    pais pelo prefixo da referencia, ano da data). Titular/CPC ficariam de fora porque
    o resultado nao os carrega e busca-los custaria N consultas por item -- o texto
    executivo/narrativo fica a cargo do agente, esta funcao so entrega os numeros.
    Espelha os KPIs do app legado (total, distribuicao) na medida do que temos aqui."""
    from collections import Counter

    def _pais(ref: str) -> str:
        # 'BR-102019...', 'EP1234567', 'US-...' -> prefixo de 2 letras.
        r = (ref or "").strip().upper()
        return r[:2] if len(r) >= 2 and r[:2].isalpha() else "??"

    def _ano(item: dict) -> str | None:
        d = item.get("data_publicacao") or item.get("data_deposito")
        return str(d)[:4] if d else None

    por_pais = Counter(_pais(p.get("referencia", "")) for p in patentes)
    por_fonte: Counter = Counter()
    for p in patentes:
        for f in p.get("fontes", [p.get("fonte")]):
            if f:
                por_fonte[f] += 1
    por_ano = Counter(a for a in (_ano(p) for p in patentes) if a)

    return {
        "familias_de_patente": len(patentes),
        "documentos_npl": len(npl),
        "por_pais": dict(por_pais.most_common()),
        "por_fonte": dict(por_fonte.most_common()),
        "por_ano_deposito_ou_publicacao": dict(sorted(por_ano.items())),
        "nota": ("KPIs deterministicos do conjunto retornado. Titular e CPC nao entram "
                 "aqui -- o resultado nao os traz e busca-los custaria uma consulta por "
                 "item; peca inpi_processo/inpi_perfil_titular se precisar deles."),
    }


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

    # Normaliza datas a ISO-string LOGO na coleta: as fontes reais (INPI via DuckDB,
    # EPO) devolvem objetos date, e todo o resto (dedup ordena por data, ordenacao
    # final, comparacao com data_critica) mistura isso com strings '9999'/'AAAA-MM-DD'
    # -> 'date < str' TypeError. Coagir aqui, num lugar so, conserta todos os pontos.
    for item in brutos + npl:
        for campo in ("data_publicacao", "data_deposito"):
            if item.get(campo) is not None:
                item[campo] = str(item[campo])[:10]

    cobertura["ppubs"] = {
        "executou": False,
        "motivo": ("Fora de escopo desta fase: sem cliente Python direto reusavel "
                   "para PPUBS/BRS neste repo. Rode manualmente via servidor MCP "
                   "'uspto' (ppubs_search_patents). TODO: integrar quando houver "
                   "wrapper Python."),
    }

    deduplicado = _deduplicar_por_familia(brutos)

    if data_critica:
        # A data de um resultado pode voltar como date/datetime (EPO/INPI reais) ou
        # string; data_critica e string 'AAAA-MM-DD'. Comparar date < str levanta
        # TypeError -- o teste nao pegava porque mockava tudo como string. Coage os dois
        # lados a ISO-string (comparacao lexicografica de datas ISO e correta).
        alvo = str(data_critica)[:10]

        def _anterior(data):
            return (str(data)[:10] < alvo) if data else None

        for item in deduplicado:
            item["anterior_a_data_critica"] = _anterior(
                item.get("data_publicacao") or item.get("data_deposito"))
        for item in npl:
            item["anterior_a_data_critica"] = _anterior(item.get("data_publicacao"))

    deduplicado.sort(key=lambda i: (
        -len(i["conceitos_encontrados"]),
        i.get("data_publicacao") or i.get("data_deposito") or "9999",
    ))

    return {
        "resumo_executivo": _resumo_executivo(deduplicado, npl),
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
