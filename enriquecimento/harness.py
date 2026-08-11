"""Harness de enriquecimento on-demand: número -> fontes -> normaliza -> grava.

Por que existe: é o ponto único que as MCP tools (inpi_reivindicacoes,
inpi_citacoes) chamam quando o store ainda não tem o número pedido. NÃO roda
em lote/agendado -- cada número só é buscado na rede na primeira vez que
alguém pergunta por ele; nas próximas, vem do store (arquivo local ou
MotherDuck). Ver decisão de volume no plano: on-demand + cache, batch fica
para depois.

ROTEAMENTO POR JURISDIÇÃO (F1 do plano de refino 2026-08): a fonte primária
de reivindicações muda conforme a jurisdição do número, detectada pelo
prefixo (`detectar_jurisdicao`):
  - US: Google Patents (kinds US) é a única fonte aqui. Sem fallback de rede
    -- o texto oficial (USPTO PPUBS) é uma tool MCP separada
    (`uspto.ppubs_get_full_document`) que o AGENTE chama, não este harness;
    a mensagem de falha aponta para ela em vez de silenciar a lacuna.
  - EP/WO: o EPO OPS (`epo_texto_integral`) é a fonte OFICIAL para essas
    duas jurisdições (ao contrário de BR/US, onde normalmente não tem nada)
    -- tentado primeiro; Google Patents (kinds EP/WO) é o fallback.
  - BR: como antes deste plano -- Google Patents (kinds BR) primeiro, família
    INPADOC + `epo_texto_integral` como fallback (cobre BR com passagem
    PCT/WO). BR-only sem família internacional não tem fonte de texto
    integral nenhuma -- a mensagem final aponta para o PDF salvo manualmente
    (fonte 3 de `inpi_reivindicacoes`), não apenas declara falha.
"""

from __future__ import annotations

from enriquecimento import store
from enriquecimento.fontes import google_patents
from enriquecimento.fontes.familia_texto import buscar_claims_via_familia
from enriquecimento.fontes.google_patents import ResultadoClaims, detectar_jurisdicao


def _buscar_epo_direto(numero_normalizado: str) -> ResultadoClaims:
    """Texto integral EPO OPS direto para um número JÁ EP/WO -- sem passar por
    resolução de família (essa só faz sentido partindo de um número BR, ver
    `familia_texto.buscar_claims_via_familia`; aqui o próprio número já é o
    membro EP/WO)."""
    from enriquecimento.fontes.google_patents import quadro_reivindicatorio
    from epo.epo_mcp import epo_texto_integral

    resp = epo_texto_integral(numero_normalizado, secao="claims")
    if resp.get("disponivel") and resp.get("texto"):
        return ResultadoClaims(
            ok=True, doc_id=numero_normalizado, fonte="epo_texto_integral",
            reivindicacoes=quadro_reivindicatorio(resp["texto"]),
        )
    return ResultadoClaims(
        ok=False, doc_id=None, fonte="epo_texto_integral",
        mensagem=resp.get("mensagem") or f"{numero_normalizado}: sem texto integral no EPO OPS",
    )


def _gravar_sem_texto(numero_normalizado: str, mensagem: str) -> dict:
    store.gravar_claims(numero_normalizado, fonte="nenhuma", doc_id=None,
                         reivindicacoes=[], status="sem_texto", mensagem=mensagem)
    return store.ler_claims(numero_normalizado)


def _gravar_ok(numero_normalizado: str, resultado: ResultadoClaims) -> dict:
    store.gravar_claims(numero_normalizado, resultado.fonte, resultado.doc_id,
                         resultado.reivindicacoes, status="ok")
    return store.ler_claims(numero_normalizado)


def enriquecer_claims(numero_normalizado: str, forcar: bool = False) -> dict:
    """Garante que o store tem as reivindicações deste número, buscando na
    rede se preciso. `forcar=True` ignora o que já está gravado e busca de
    novo (útil quando uma fonte que antes falhou pode ter mudado).

    A rota de busca depende da jurisdição do número (ver docstring do
    módulo) -- detectada automaticamente, sem parâmetro extra na assinatura
    (não quebra `inpi_reivindicacoes`, que só passa o número)."""
    if not forcar:
        existente = store.ler_claims(numero_normalizado)
        if existente is not None:
            return existente

    jurisdicao = detectar_jurisdicao(numero_normalizado)

    if jurisdicao == "US":
        primario = google_patents.buscar_claims(numero_normalizado, jurisdicao="US")
        if primario.ok:
            return _gravar_ok(numero_normalizado, primario)
        mensagem = (
            f"google_patents (US): {primario.mensagem}. Se a página não existe/não tem "
            "seção de Claims reconhecida, isso é cobertura do Google Patents, não erro "
            "de rede -- tente uspto.ppubs_get_full_document (tool MCP do USPTO, texto "
            "integral oficial) antes de declarar o documento sem texto disponível."
        )
        return _gravar_sem_texto(numero_normalizado, mensagem)

    if jurisdicao in ("EP", "WO"):
        primario = _buscar_epo_direto(numero_normalizado)
        if primario.ok:
            return _gravar_ok(numero_normalizado, primario)
        fallback = google_patents.buscar_claims(numero_normalizado, jurisdicao=jurisdicao)
        if fallback.ok:
            return _gravar_ok(numero_normalizado, fallback)
        mensagem = (
            f"epo_texto_integral: {primario.mensagem} | google_patents ({jurisdicao}): "
            f"{fallback.mensagem}. Nenhuma das duas fontes oficiais para {jurisdicao} tem "
            "o documento -- cobertura, não falha de rede."
        )
        return _gravar_sem_texto(numero_normalizado, mensagem)

    # BR (padrão sem prefixo reconhecido): Google Patents primeiro, família
    # INPADOC + EPO como fallback -- comportamento anterior a este fix.
    primario = google_patents.buscar_claims(numero_normalizado, jurisdicao="BR")
    if primario.ok:
        return _gravar_ok(numero_normalizado, primario)

    fallback = buscar_claims_via_familia(numero_normalizado)
    if fallback.ok:
        return _gravar_ok(numero_normalizado, fallback)

    mensagem = (
        f"google_patents: {primario.mensagem} | família (EPO): {fallback.mensagem}. "
        "Provável lacuna de cobertura (não erro de rede): pedido BR-only sem família "
        "PCT/WO/EP publicada não tem texto integral em nenhuma fonte automática aqui -- "
        "só o PDF oficial salvo manualmente resolve (inpi_reivindicacoes tenta essa "
        "fonte 3 automaticamente antes de devolver ao operador)."
    )
    return _gravar_sem_texto(numero_normalizado, mensagem)


def enriquecer_citacoes(numero_normalizado: str, forcar: bool = False) -> dict:
    """Mesma lógica de cache-then-network de enriquecer_claims, para
    citações. Lista vazia gravada é um resultado válido (documento sem
    citação registrada) -- só tenta a fonte de novo se `forcar=True`.

    Google Patents é a única fonte de citações aqui, para qualquer
    jurisdição -- só precisa do doc_id certo (por isso passa `jurisdicao`
    detectada, mesmo fix de roteamento do F1)."""
    if not forcar:
        existentes = store.ler_citacoes(numero_normalizado)
        if existentes:
            return {"numero_normalizado": numero_normalizado, "citacoes": existentes,
                     "mensagem": None}

    jurisdicao = detectar_jurisdicao(numero_normalizado)
    resultado = google_patents.buscar_citacoes(numero_normalizado, jurisdicao=jurisdicao)
    if resultado.ok:
        store.gravar_citacoes(
            numero_normalizado, resultado.fonte,
            [{"tipo": c["tipo"], "doc_citado": c["doc_citado"]} for c in resultado.citacoes],
        )
    return {
        "numero_normalizado": numero_normalizado,
        "citacoes": store.ler_citacoes(numero_normalizado),
        "mensagem": None if resultado.ok else resultado.mensagem,
    }
