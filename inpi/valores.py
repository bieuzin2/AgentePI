"""Parse de valor monetario da ficha do pePI, com descarte de lixo.

Os dois ledgers guardam valor em formatos diferentes: ficha_anuidades como
'$1,645.00' (milhar com virgula, centavos com ponto) e ficha_peticoes como
'419.0' (float cru). Apesar do cifrao, a MOEDA e R$ -- a mediana da anuidade e
R$ 295, coerente com a tabela de retribuicoes do INPI, nao com USD.

Ha lixo real: em ~18 linhas o numero da GRU (ex.: 921002573202) vazou para o
campo valor, o que estoura qualquer soma (total sobe de ~R$ 583 mi para R$ 5,4
trilhoes). Por isso o parse REJEITA valores implausiveis: uma anuidade/peticao
de patente nao chega a R$ 1 milhao. parse_valor devolve None para lixo, vazio e
formato irreconhecivel -- quem soma conta quantos descartou e reporta.
"""

from __future__ import annotations

import re

MOEDA = "R$ (conforme a ficha do pePI; cifrao no dado bruto, mas mediana ~R$295 = BRL, a confirmar)"

# Teto sano: nenhuma retribuicao unica do INPI chega a isso. Acima = lixo (GRU no
# campo valor, tipicamente). Ajuste aqui se algum dia houver taxa legitima maior.
TETO_SANO = 1_000_000.0

_LIMPA = re.compile(r"[R$\s]")


def parse_valor(bruto: str | None) -> float | None:
    """'$1,645.00' -> 1645.0 ; '419.0' -> 419.0 ; lixo/vazio/GRU -> None.

    Trata a virgula como separador de MILHAR (o formato da ficha_anuidades usa
    ponto para centavos): remove virgulas antes do cast. Rejeita o que passar do
    TETO_SANO (provavel numero de GRU vazado)."""
    if not bruto:
        return None
    s = _LIMPA.sub("", str(bruto)).replace(",", "")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if v < 0 or v > TETO_SANO:
        return None
    return v


def demo() -> None:
    # Os dois formatos REAIS da base:
    assert parse_valor("$1,645.00") == 1645.0   # ficha_anuidades
    assert parse_valor("419.0") == 419.0        # ficha_peticoes
    assert parse_valor("$295.00") == 295.0
    assert parse_valor("$2,800.00") == 2800.0
    assert parse_valor("921002573202") is None  # GRU vazada no campo valor
    assert parse_valor("") is None
    assert parse_valor(None) is None
    assert parse_valor("abc") is None
    print("ok")


if __name__ == "__main__":
    demo()
