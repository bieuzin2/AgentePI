"""Projecao de anuidades de patente brasileira (arts. 40, 84, 85 e 87 da LPI).

POR QUE ISTO EXISTE, e por que e diferente do prazo de exigencia:

O agente se recusa a calcular prazo de exigencia porque aquilo depende de codigo de
despacho ambiguo -- 432 codigos, nenhum consistente, 0,83% de cobertura. Anuidade e
outra coisa: depende de UMA data (o deposito) e de UMA regra legal fixa. E
deterministico, reproduzivel e auditavel em trinta segundos.

O QUE ISTO NAO E: nao e a conta do INPI, e nao substitui o controle de prazos do
escritorio. O INPI nao publica vencimento futuro -- publica consequencia.

SEMANTICA DOS DESPACHOS DE ANUIDADE (verificada, e contraintuitiva):
8.6 e 21.6 NAO sao notificacao de cobranca. Sao o proprio arquivamento do pedido
(8.6) ou a extincao da patente (21.6) por falta de pagamento -- com 3 meses para
requerer restauracao (art. 87, GRU 208). Logo, a anuidade citada neles NAO foi paga.
Confirmado na base: em 90% dos pares '8.6 -> extincao posterior', a mesma anuidade
reaparece como nao recolhida. Ler '18a anuidade' como 'as 17 primeiras foram pagas'
inverte o significado e pula exatamente o que esta em aberto.

CALIBRACAO CONTRA O DADO REAL (2026-07-25, 285.409 despachos de anuidade):
o despacho da Na anuidade aparece com mediana de -0,04 ano do aniversario N do
deposito (p10 -0,18; p90 +0,74). A 3a anuidade e a primeira observada (25.896 casos),
o que confirma o art. 84. Casos PCT seguem a MESMA distribuicao (145.460 no delta
zero): o INPI ja grava em data_deposito a data internacional.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

# Art. 84: devida a partir do inicio do terceiro ano do deposito.
PRIMEIRA_ANUIDADE = 3
# Art. 84 par. 2: periodo ordinario de 3 meses a contar do inicio do periodo anual.
MESES_ORDINARIO = 3
# Art. 84 par. 2 / art. 85: prazo complementar de 6 meses com retribuicao adicional.
MESES_COMPLEMENTAR = 6
# Art. 87: prazo para requerer restauracao apos arquivamento/extincao por anuidade.
MESES_RESTAURACAO = 3
# Art. 40: vigencia contada do deposito.
VIGENCIA_ANOS = {"PI": 20, "MU": 15}

# Despachos que ENCERRAM o processo.
CODIGOS_TERMINAIS = {
    "9.2",                                                # indeferimento
    "11.1", "11.1.1", "11.2", "11.5", "11.6", "11.6.1",   # arquivamentos
    "24.1", "24.2", "24.3", "24.5", "24.7", "24.10",      # extincoes
    "8.6", "21.6",                                        # arquivamento/extincao por anuidade
}

# Despachos que REVERTEM ou desmentem um terminal anterior. Um terminal so vale se
# nenhum destes veio depois. Nao use "qualquer despacho posterior": 115.623 processos
# tem despachos posteriores ao terminal que sao notificacoes do proprio arquivamento.
CODIGOS_REVERSAO = {
    "16.1",            # publicacao de vigencia -- so existe se foi concedida
    "100", "100.1",    # recurso conhecido e provido
    "9.1",             # carta-patente
    "8.5",             # complementacao de anuidade -- o INPI ainda cobra
    "15.22", "15.22.1",  # devolucao de prazo / justa causa
}

# Despachos que citam anuidade EM ABERTO (arquivamento, extincao, nao recolhimento).
CODIGOS_DEBITO_ANUIDADE = {"8.6", "21.6", "8.11", "8.12", "24.1", "24.2", "24.3", "24.7"}
# Pagamento a menor: o valor devido existe, mas nao e a anuidade inteira.
CODIGOS_COMPLEMENTACAO = {"8.5"}


def _mais_meses(d: date, meses: int) -> date:
    """Soma meses preservando o dia; encurta para o ultimo dia do mes quando preciso."""
    ano = d.year + (d.month - 1 + meses) // 12
    mes = (d.month - 1 + meses) % 12 + 1
    dia = d.day
    while True:
        try:
            return date(ano, mes, dia)
        except ValueError:
            dia -= 1  # 31 de marco + 1 mes -> 30 de abril


def _mais_anos(d: date, anos: int) -> date:
    try:
        return d.replace(year=d.year + anos)
    except ValueError:
        return d.replace(year=d.year + anos, day=28)  # 29/02 em ano nao bissexto


def natureza(numero_inpi: str) -> str:
    """PI (invencao, 20 anos) ou MU (modelo de utilidade, 15 anos).

    Verificado contra o despacho 16.1, que publica a vigencia real:
      prefixo 10/11/12/13 -> '20 (vinte) anos'  (110.481 casos, 3 excecoes)
      prefixo 20/21/22    -> '15 (quinze) anos' (5.765 casos, 37 excecoes)
    Os prefixos 21 e 22 sao poucos (504 processos) mas 100% modelo de utilidade --
    trata-los como invencao dava 5 anos a mais de vigencia e teto de 20 anuidades.
    """
    n = (numero_inpi or "").upper()
    if n.startswith(("MU", "MI")):
        # MI e modelo industrial do regime pre-LPI; nao ha 16.1 na base para conferir,
        # entao 15 anos aqui e a hipotese conservadora, nao um fato verificado.
        return "MU"
    if n.startswith(("PI", "C", "PP")):
        return "PI"
    if n[:2] in ("20", "21", "22"):
        return "MU"
    return "PI"


@dataclass
class Janela:
    anuidade: int
    inicio_ordinario: date
    fim_ordinario: date
    fim_complementar: date

    def dict(self) -> dict:
        return {
            k: (v.isoformat() if isinstance(v, date) else v)
            for k, v in asdict(self).items()
        }


def janela(data_deposito: date, n: int) -> Janela:
    """Periodo de pagamento da n-esima anuidade.

    O periodo anual n comeca no aniversario (n-1) do deposito. Ordinario: 3 meses.
    Complementar: mais 6, com retribuicao adicional (art. 84 par. 2 / art. 85).
    """
    if n < PRIMEIRA_ANUIDADE:
        raise ValueError(
            f"A primeira anuidade devida e a {PRIMEIRA_ANUIDADE}a (art. 84 da LPI); "
            f"pedida a {n}a."
        )
    inicio = _mais_anos(data_deposito, n - 1)
    fim_ord = _mais_meses(inicio, MESES_ORDINARIO)
    return Janela(n, inicio, fim_ord, _mais_meses(fim_ord, MESES_COMPLEMENTAR))


def fim_vigencia(data_deposito: date, numero_inpi: str) -> date:
    """Art. 40: 20 anos (invencao) ou 15 (modelo de utilidade), do deposito.

    Nao aplica o par. unico do art. 40 (prazo minimo contado da concessao), declarado
    inconstitucional pelo STF na ADI 5529 em 2021. Quando existir despacho 16.1 no
    processo, ele e a fonte melhor -- traz o prazo publicado pelo proprio INPI.
    """
    return _mais_anos(data_deposito, VIGENCIA_ANOS[natureza(numero_inpi)])


def projetar(
    data_deposito: date,
    numero_inpi: str,
    hoje: date,
    em_aberto: set[int] | None = None,
    complementacao: set[int] | None = None,
    encerrado_em: date | None = None,
    quantas_futuras: int = 3,
) -> dict:
    """Projeta a situacao de anuidades de um processo.

    Args:
        data_deposito: data-base. Sem ela nao ha projecao.
        numero_inpi: define 20 ou 15 anos de vigencia.
        hoje: data de referencia. Explicita de proposito -- nenhuma funcao aqui chama
            date.today(), para que o resultado seja reproduzivel e testavel.
        em_aberto: anuidades citadas em despacho de debito (8.6/21.6/24.x). Elas NAO
            foram pagas -- e o motivo do arquivamento ou da extincao.
        complementacao: anuidades com pagamento a menor (8.5).
        encerrado_em: data do terminal em vigor, se houver e nao tiver sido revertido.
        quantas_futuras: quantas janelas ainda-nao-iniciadas devolver.
    """
    em_aberto = set(em_aberto or ())
    complementacao = set(complementacao or ())
    nat = natureza(numero_inpi)
    teto = VIGENCIA_ANOS[nat]
    fim = fim_vigencia(data_deposito, numero_inpi)

    base = {
        "data_deposito": data_deposito.isoformat(),
        "natureza": nat,
        "fim_vigencia_calculado": fim.isoformat(),
        "regra": (
            "Art. 84 da LPI: devida a partir do inicio do 3o ano do deposito. Periodo "
            f"ordinario de {MESES_ORDINARIO} meses a contar do aniversario do deposito, "
            f"mais {MESES_COMPLEMENTAR} meses de prazo complementar com retribuicao "
            "adicional (art. 84 par. 2 / art. 85). Vigencia pelo art. 40."
        ),
    }

    if encerrado_em:
        r = {
            **base,
            "situacao": "encerrado",
            "encerrado_em": encerrado_em.isoformat(),
            "anuidades": [],
            "aviso": (
                "Processo com despacho terminal em vigor (arquivamento, indeferimento ou "
                "extincao) e sem despacho posterior de reversao. Nao ha anuidade a "
                "projetar. Se o arquivamento foi por falta de anuidade (8.6/21.6), cabe "
                f"restauracao em ate {MESES_RESTAURACAO} meses da publicacao (art. 87, "
                "GRU 208) -- confira a data e o texto do despacho."
            ),
        }
        if em_aberto:
            r["anuidades_em_aberto_no_encerramento"] = sorted(em_aberto)
        return r

    if hoje > fim:
        return {
            **base,
            "situacao": "vigencia_expirada",
            "anuidades": [],
            "aviso": "A vigencia calculada ja terminou. Confira o despacho 16.1.",
        }

    linhas, vencidas_sem_noticia, futuras = [], [], 0
    for n in range(PRIMEIRA_ANUIDADE, teto + 1):
        j = janela(data_deposito, n)
        d = j.dict()

        if n in em_aberto:
            d["status"] = "em_debito_notificado"
            d["nota"] = (
                "O INPI publicou despacho apontando esta anuidade como nao recolhida. "
                f"Cabe restauracao em ate {MESES_RESTAURACAO} meses da publicacao "
                "(art. 87, GRU 208)."
            )
        elif n in complementacao:
            d["status"] = "complementacao_devida"
            d["nota"] = "Despacho 8.5: retribuicao recolhida a menor; falta complementar."
        elif j.fim_complementar < hoje:
            # Nao ha noticia no dado -- pagamento em dia nao gera despacho. Nao
            # afirmamos que foi paga; apenas que nada apareceu.
            vencidas_sem_noticia.append(n)
            continue
        elif j.inicio_ordinario <= hoje <= j.fim_ordinario:
            d["status"] = "periodo_ordinario_corrente"
        elif j.fim_ordinario < hoje <= j.fim_complementar:
            d["status"] = "prazo_complementar_corrente"
            d["alerta"] = (
                "Periodo ordinario encerrado; pagamento so com retribuicao adicional."
            )
        else:
            if futuras >= quantas_futuras:
                continue
            futuras += 1
            d["status"] = "futura"

        d["dias_ate_fim_complementar"] = (j.fim_complementar - hoje).days
        linhas.append(d)

    linhas.sort(key=lambda x: x["fim_complementar"])
    return {
        **base,
        "situacao": "ativo",
        "anuidades": linhas,
        "anuidades_vencidas_sem_noticia": vencidas_sem_noticia,
        "aviso": (
            "PROJECAO CALCULADA, nao consultada -- o INPI nao publica vencimento futuro. "
            "'em_debito_notificado' vem de despacho publicado e e o motivo de um "
            "arquivamento ou extincao. 'anuidades_vencidas_sem_noticia' sao periodos que "
            "ja passaram sem que nada aparecesse na base: pagamento em dia NAO gera "
            "despacho, entao o silencio nao prova pagamento nem inadimplencia. Confira na "
            "GRU e no controle de prazos do escritorio. Nao substitui o docketing nem o "
            "procurador responsavel."
        ),
    }
