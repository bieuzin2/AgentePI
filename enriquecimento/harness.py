"""Harness de enriquecimento on-demand: número -> fontes -> normaliza -> grava.

Por que existe: é o ponto único que as MCP tools (inpi_reivindicacoes,
inpi_citacoes) chamam quando o store ainda não tem o número pedido. NÃO roda
em lote/agendado -- cada número só é buscado na rede na primeira vez que
alguém pergunta por ele; nas próximas, vem do store (arquivo local ou
MotherDuck). Ver decisão de volume no plano: on-demand + cache, batch fica
para depois.
"""

from __future__ import annotations

from enriquecimento import store
from enriquecimento.fontes import google_patents
from enriquecimento.fontes.familia_texto import buscar_claims_via_familia


def enriquecer_claims(numero_normalizado: str, forcar: bool = False) -> dict:
    """Garante que o store tem as reivindicações deste número, buscando na
    rede se preciso. `forcar=True` ignora o que já está gravado e busca de
    novo (útil quando uma fonte que antes falhou pode ter mudado)."""
    if not forcar:
        existente = store.ler_claims(numero_normalizado)
        if existente is not None:
            return existente

    primario = google_patents.buscar_claims(numero_normalizado)
    if primario.ok:
        store.gravar_claims(numero_normalizado, primario.fonte, primario.doc_id,
                             primario.reivindicacoes, status="ok")
        return store.ler_claims(numero_normalizado)

    fallback = buscar_claims_via_familia(numero_normalizado)
    if fallback.ok:
        store.gravar_claims(numero_normalizado, fallback.fonte, fallback.doc_id,
                             fallback.reivindicacoes, status="ok")
        return store.ler_claims(numero_normalizado)

    mensagem = f"google_patents: {primario.mensagem} | família (EPO): {fallback.mensagem}"
    store.gravar_claims(numero_normalizado, fonte="nenhuma", doc_id=None,
                         reivindicacoes=[], status="sem_texto", mensagem=mensagem)
    return store.ler_claims(numero_normalizado)


def enriquecer_citacoes(numero_normalizado: str, forcar: bool = False) -> dict:
    """Mesma lógica de cache-then-network de enriquecer_claims, para
    citações. Lista vazia gravada é um resultado válido (documento sem
    citação registrada) -- só tenta a fonte de novo se `forcar=True`."""
    if not forcar:
        existentes = store.ler_citacoes(numero_normalizado)
        if existentes:
            return {"numero_normalizado": numero_normalizado, "citacoes": existentes,
                     "mensagem": None}

    resultado = google_patents.buscar_citacoes(numero_normalizado)
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
