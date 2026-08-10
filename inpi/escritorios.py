"""Normalizacao de nome de escritorio e de titular na base do INPI.

O PROBLEMA, medido: a tabela `procuradores` tem ~17,5 mil grafias distintas para algo
como 10 mil escritorios reais. A Clarke Modet aparece em dezenas de grafias -- variacoes
de caixa, pontuacao, "do Brasil" vs "Propriedade Intelectual", espacos duplos, e ate
espaco no inicio (':CLARKE, MODET...'). Sem agrupar, qualquer estatistica de mercado
esta errada e a carteira do escritorio sai fragmentada.

DUAS CAMADAS, porque uma nao basta:

1. Normalizacao deterministica (esta funcao): caixa, acento, pontuacao e sufixos
   societarios/descritivos. Reduz ~17,5 mil -> ~10 mil chaves (-42%) e junta as
   dezenas de grafias que referenciam a firma numa so chave.

2. Apelidos revisados (referencias/escritorios-apelidos.csv): erro de digitacao nao
   tem regra. 'CLARK MODET', 'CLAKE MODET', 'CLARCKE MODET', 'CLARKE MODETO',
   'CLARKE MONDET', 'CLARHE MODET', 'CLARKE MOET' sao todos a mesma empresa, e
   nenhuma normalizacao razoavel junta isso sem juntar tambem coisas diferentes.
   Fuzzy matching automatico aqui seria pior: uniria escritorios homonimos de
   familias distintas (ha varios 'LEONARDOS' que sao bancas separadas). Entao a
   ponte e uma tabela revisada por humano, no mesmo espirito da tabela de codigos
   de despacho.

   ESSA MESMA TABELA carrega tambem AFILIACOES deliberadas, nao so typos: um agente
   pessoa fisica cujos casos contam para a banca (ex.: 'ORLANDO DE SOUZA' e 'FLAVIA
   SALIM LOPES' -> 'CLARKE MODET', coluna 'observacao' = "agente da casa - confirmado
   pelo usuario"). Por isso a carteira Clarke soma ~44,7 mil processos e nao so as
   ~25,8 mil grafias que trazem a palavra "clarke": ~18,9 mil vem desses agentes.
   Isso e curadoria endossada, NAO erro -- nao remova as duas linhas achando que sao
   ruido. A composicao (firma vs agente afiliado) e exposta por `apelidos_com_motivo`
   e pelos campos `composicao` de inpi_escritorio_resolver/inpi_carteira, para o
   numero nunca chegar opaco ao agente.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

APELIDOS = Path(__file__).resolve().parent / "referencias" / "escritorios-apelidos.csv"

# Removidos porque descrevem a natureza juridica ou o ramo, nao identificam a banca.
# Ordem importa: os compostos saem antes dos simples.
_SUFIXOS = [
    "SOCIEDADE DE ADVOGADOS", "ADVOGADOS ASSOCIADOS", "PROPRIEDADE INTELECTUAL",
    "PROPRIEDADE INDUSTRIAL", "MARCAS E PATENTES", "PATENTES E MARCAS",
    "CONSULTORIA EM PROPRIEDADE", "SERVICOS DE PROPRIEDADE",
    "AGENCIA DE PROPRIEDADE", "ASSESSORIA EMPRESARIAL",
    "DO BRASIL", "BRASIL", "ADVOGADOS", "ADVOCACIA", "CONSULTORES",
    "ASSOCIADOS", "LTDA", "EIRELI", "EPP", "ME", "SS", "S A", "SA", "CIA",
    "E CIA", "INC",
]

# Um unico padrao alternado, compilado uma vez. A versao ingenua (4 passes x 25
# re.sub) custava 277 us por nome -- 2,3 min so para normalizar os ~500 mil nomes
# distintos de depositante na carga.
_RE_SUFIXOS = re.compile(
    r"(?:^|(?<= ))(?:" + "|".join(re.escape(s) for s in sorted(_SUFIXOS, key=len, reverse=True)) + r")(?= |$)"
)
_RE_NAO_ALNUM = re.compile(r"[^A-Z0-9 ]")
_RE_ESPACOS = re.compile(r"\s+")

_cache_apelidos: dict[str, str] | None = None


def _apelidos() -> dict[str, str]:
    global _cache_apelidos
    if _cache_apelidos is None:
        _cache_apelidos = {}
        if APELIDOS.exists():
            with APELIDOS.open(encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    v, c = r["variante"].strip().upper(), r["canonico"].strip().upper()
                    if v and c:
                        _cache_apelidos[v] = c
    return _cache_apelidos


def apelidos_com_motivo() -> dict[str, dict]:
    """Como _apelidos, mas carrega tambem a 'observacao' de cada mapeamento -- a
    proveniencia da curadoria. E o que distingue um erro de digitacao ('CLAKE MODET')
    de uma AFILIACAO deliberada (um agente pessoa fisica cujos casos contam para a
    banca, ex.: 'ORLANDO DE SOUZA' -> 'CLARKE MODET', observacao 'agente da casa').
    Sem isto, a carteira devolve um numero que o agente nao consegue explicar."""
    saida: dict[str, dict] = {}
    if APELIDOS.exists():
        with APELIDOS.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                v = (r.get("variante") or "").strip().upper()
                if not v:
                    continue
                saida[v] = {
                    "canonico": (r.get("canonico") or "").strip().upper(),
                    "observacao": (r.get("observacao") or "").strip(),
                }
    return saida


def normalizar(nome: str | None) -> str:
    """Chave de agrupamento de um nome de escritorio ou titular."""
    if not nome:
        return ""
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().upper()
    s = _RE_ESPACOS.sub(" ", _RE_NAO_ALNUM.sub(" ", s)).strip()
    # Repete porque remover um sufixo pode expor outro ("... LTDA ME" -> "... ME").
    for _ in range(4):
        novo = _RE_ESPACOS.sub(" ", _RE_SUFIXOS.sub(" ", s)).strip()
        if novo == s:
            break
        s = novo
    return _apelidos().get(s, s)
