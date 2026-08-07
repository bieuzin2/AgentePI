"""Proveniencia de titular: dado curado Clarke Modet vs normalizacao automatica.

A chave canonica de titular ja existe (tabela `titulares`, 3 camadas -- ver
ingest.py::_materializa_titulares). Este modulo NAO cria outra normalizacao;
so responde: esta chave e um cliente CURADO da Clarke Modet (revisado por
humano em referencias/clientes-clarke.csv) ou e agrupamento automatico?

Toda tool que faz matching por nome de titular anexa `resolver(chave_de(nome))`
ao retorno -- o nivel de confianca viaja NO DADO, o agente conversacional so
renderiza o rodape (curada = cliente Clarke Modet; automatica = qualquer outro).
"""

from __future__ import annotations

import csv
from pathlib import Path

CLIENTES = Path(__file__).resolve().parent / "referencias" / "clientes-clarke.csv"

_cache_clientes: dict[str, str] | None = None


def _clientes() -> dict[str, str]:
    """chave_canonica -> nome_exibicao. CSV ausente = nenhum cliente curado."""
    global _cache_clientes
    if _cache_clientes is None:
        _cache_clientes = {}
        if CLIENTES.exists():
            with CLIENTES.open(encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    chave = (r.get("chave_canonica") or "").strip()
                    if chave:
                        _cache_clientes[chave] = (r.get("nome_exibicao") or chave).strip()
    return _cache_clientes


def chaves_de(nome: str) -> list[dict]:
    """Chaves canonicas que o texto do nome casa, mais processada primeiro.
    Fonte unica de resolucao nome->chave (perfil.py e saude.py consomem)."""
    from inpi.consulta import _linhas

    return _linhas(
        """SELECT t.chave, count(DISTINCT dp.numero_inpi) processos,
                  arg_max(dp.depositante, dp.numero_inpi) exemplo
           FROM depositantes dp JOIN titulares t ON t.original = dp.depositante
           WHERE dp.depositante ILIKE ?
           GROUP BY t.chave ORDER BY processos DESC LIMIT 12""",
        [f"%{nome.strip()}%"],
    )


def chave_de(nome: str) -> str | None:
    """A chave canonica com mais processos que o nome casa, ou None."""
    c = chaves_de(nome)
    return c[0]["chave"] if c else None


def resolver(chave: str | None) -> dict:
    """Bloco de proveniencia para uma chave canonica de titular."""
    clientes = _clientes()
    if chave and chave in clientes:
        return {"nivel": "curada", "chave": chave,
                "nome_exibicao": clientes[chave],
                "nota": "cliente Clarke Modet com curadoria humana"}
    return {"nivel": "automatica", "chave": chave,
            "nota": "agrupamento automatico de grafias -- confira a grafia se o numero importar"}


def relacionados(chave: str | None) -> list[dict]:
    """Clientes curados que PODEM ser entidades relacionadas (mesmo primeiro
    nome, ex: MOTOROLA / MOTOROLA MOBILITY / MOTOROLA SOLUTIONS). Sugestao
    informativa -- NUNCA somados em contagem alguma. Sem fuzzy."""
    if not chave:
        return []
    prefixo = chave.replace("CNPJ:", "").split(" ")[0]
    if len(prefixo) < 4:  # prefixo curto demais junta coisa distinta
        return []
    return [
        {"chave": c, "nome_exibicao": n, "nao_somados_na_contagem": True}
        for c, n in _clientes().items()
        if c != chave and c.split(" ")[0] == prefixo
    ]


def demo() -> None:
    assert resolver(None)["nivel"] == "automatica"
    r = resolver("HUAWEI TECHNOLOGIES")
    assert r["nivel"] in ("curada", "automatica")  # depende do CSV revisado
    rel = relacionados("MOTOROLA")
    assert all(x["nao_somados_na_contagem"] for x in rel)
    print(f"OK  resolver e relacionados ({len(_clientes())} clientes curados carregados)")


if __name__ == "__main__":
    demo()
