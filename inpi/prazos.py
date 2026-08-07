"""Motor de prazos e anuidades: projecao art. 84, prazos de carteira, novidades.

Extraido de inpi_mcp.py na modularizacao da Fase 0. Logica e docstrings de tool
inalteradas -- so mudou o arquivo que as contem.
"""

from __future__ import annotations

from datetime import date, timedelta

from inpi import anuidades as anu
from inpi import escritorios as esc
from inpi import jurisdicoes as jur
from inpi.consulta import _linhas, _marca_anulacoes, _anuidades_citadas, _prazo_declarado, normaliza_numero
from inpi.db import con
from inpi.mcp_app import mcp
from inpi.relatorios import gerar_prazos_pdf
from inpi.titulares import chave_de

# ---------------------------------------------------------------------------
# Anuidades: projecao (a unica projecao de prazo que este servidor faz)
# ---------------------------------------------------------------------------


def _estado_de(num: str, desp: list[dict], data_deposito) -> dict:
    """Deriva o estado de UM processo a partir dos despachos ja carregados.

    Nao consulta o banco -- por isso serve igual para um caso e para uma carteira
    inteira. Ver `_carregar_lote`, que faz a leitura em duas queries.
    """
    _marca_anulacoes(desp)
    vivos = [d for d in desp if not d.get("anulado_em")]

    em_aberto: set[int] = set()
    complementacao: set[int] = set()
    for d in vivos:
        cod = str(d.get("codigo_despacho"))
        citadas = _anuidades_citadas(d.get("complemento_despacho"))
        if cod in anu.CODIGOS_DEBITO_ANUIDADE:
            em_aberto.update(citadas)
        elif cod in anu.CODIGOS_COMPLEMENTACAO:
            complementacao.update(citadas)

    # Terminal so vale se nada o reverteu depois. Indeferimento cai por recurso
    # (codigo 100), arquivamento por restauracao. O PI0803071 foi indeferido em 2019,
    # teve recurso provido em 2023 e recebeu anuidade em 2026 -- tratar como encerrado
    # responderia "nao ha anuidade a pagar" sobre patente concedida e viva.
    terminal = None
    for d in vivos:
        cod = str(d.get("codigo_despacho"))
        if cod in anu.CODIGOS_TERMINAIS:
            terminal = d
        elif terminal and cod in anu.CODIGOS_REVERSAO:
            terminal = None

    return {
        "numero_inpi": num,
        "data_deposito": data_deposito,
        "anuidades_em_aberto": sorted(em_aberto),
        "anuidades_complementacao": sorted(complementacao),
        "encerrado_em": terminal["data_rpi"] if terminal else None,
        "despacho_terminal": terminal,
        "despachos": desp,
    }


def _carregar_lote(
    numeros: list[str] | None = None,
    titular: str | None = None,
    procurador: str | None = None,
    desde: str | None = None,
) -> tuple[dict[str, dict], int]:
    """Carrega despachos e deposito de uma carteira inteira em DUAS queries.

    O laço anterior fazia 2 queries por caso: 37,3 s para os 1.864 processos da
    Petrobras. Com semi-join sao 0,35 s -- fator 100x. Passar 1.864 placeholders num
    IN(...) tambem funciona mas custa 9 s; o JOIN contra a subquery e o caminho.

    Returns:
        (estados por numero, total de casos que o criterio casou antes de qualquer corte)
    """
    if numeros:
        alvo_sql = "SELECT unnest(?::VARCHAR[]) AS numero_inpi"
        params: list = [numeros]
    elif titular:
        # Pela CHAVE canonica, nao por ILIKE de texto (mesmo motivo do branch
        # procurador abaixo): ILIKE '%huawei%' juntava "Huawei Digital Power" e
        # outras entidades distintas -- contava 5.180 processos onde a chave
        # canonica (a mesma que inpi_perfil_titular usa) conta 5.098. Todas as
        # tools que passam por _carregar_lote(titular=...) agora contam igual.
        alvo_sql = """SELECT DISTINCT dp.numero_inpi FROM depositantes dp
                      JOIN titulares t ON t.original = dp.depositante
                      WHERE t.chave = ?"""
        params = [chave_de(titular)]
    elif procurador:
        # Pela CHAVE normalizada, nao pelo nome cru. Com ILIKE no texto, "Clarke
        # Modet" trazia 2.796 casos em vez de 44.610: perdia as grafias com espaco
        # duplo, as variantes do CSV de apelidos e os agentes da casa (Orlando de
        # Souza, Flavia Salim Lopes). Relatorio de prazo com esse recorte seria pior
        # que relatorio nenhum.
        alvo_sql = """SELECT DISTINCT p.numero_inpi FROM procuradores p
                      JOIN escritorios e ON e.original = p.procurador
                      WHERE e.chave = ?"""
        params = [esc.normalizar(procurador)]
    else:
        raise ValueError("Informe numeros, titular ou procurador.")

    total = con().execute(f"SELECT count(*) FROM ({alvo_sql}) t", params).fetchone()[0]

    filtro_data = " AND d.data_rpi >= ?" if desde else ""
    p_desp = params + ([desde] if desde else [])
    desp = _linhas(
        f"""WITH alvo AS ({alvo_sql})
            SELECT d.numero_inpi, d.numero_rpi, d.data_rpi, d.codigo_despacho,
                   d.complemento_despacho
            FROM despachos d JOIN alvo USING (numero_inpi)
            WHERE 1=1{filtro_data}
            ORDER BY d.numero_inpi, d.data_rpi""",
        p_desp,
    )
    deps = {
        r["numero_inpi"]: r["dep"]
        for r in _linhas(
            f"""WITH alvo AS ({alvo_sql})
                SELECT b.numero_inpi, min(b.data_deposito) dep
                FROM biblio b JOIN alvo USING (numero_inpi)
                WHERE b.data_deposito IS NOT NULL GROUP BY 1""",
            params,
        )
    }

    por_num: dict[str, list[dict]] = {}
    for d in desp:
        por_num.setdefault(d["numero_inpi"], []).append(d)

    chaves = set(por_num) | set(deps)
    return (
        {n: _estado_de(n, por_num.get(n, []), deps.get(n)) for n in chaves},
        total,
    )


@mcp.tool()
def inpi_anuidades(numero: str, hoje: str | None = None, quantas: int = 3) -> dict:
    """PROJETA as proximas anuidades de um pedido brasileiro (art. 84 da LPI).

    USE QUANDO: perguntarem "quando vence a proxima anuidade" de um caso.

    Isto e CALCULO, nao consulta -- o INPI nao publica vencimento futuro, publica
    consequencia. A projecao parte da data de deposito e da regra do art. 84,
    calibrada contra 285.409 despachos reais. Sempre confira na GRU e no controle
    de prazos do escritorio: pagamento em dia NAO gera despacho, entao a base nao
    sabe o que ja foi pago -- so o que foi notificado.

    Args:
        numero: em qualquer formato ('BR 10 2022 010731 2', 'PI0803071', ...).
        hoje: 'AAAA-MM-DD' como referencia. Informe sempre que quiser resultado
            reproduzivel; sem isso usa a data corrente do sistema.
        quantas: quantas janelas futuras devolver (1 a 10).
    """
    num = normaliza_numero(numero)
    ref = date.fromisoformat(hoje) if hoje else date.today()
    estados, _ = _carregar_lote(numeros=[num])
    est = estados.get(num)
    if not est or not est["data_deposito"]:
        return {
            "erro": True,
            "numero_inpi": num,
            "mensagem": (
                "Sem data de deposito na base -- nao ha data-base e portanto nao ha "
                "projecao possivel. Confira o numero."
            ),
        }

    r = anu.projetar(
        data_deposito=est["data_deposito"],
        numero_inpi=num,
        hoje=ref,
        em_aberto=est["anuidades_em_aberto"],
        complementacao=est["anuidades_complementacao"],
        encerrado_em=est["encerrado_em"],
        quantas_futuras=max(1, min(quantas, 10)),
    )
    r["numero_inpi"] = num
    r["referencia"] = ref.isoformat()
    if est["despacho_terminal"]:
        t = est["despacho_terminal"]
        r["despacho_terminal"] = {
            "codigo": t["codigo_despacho"],
            "data_rpi": str(t["data_rpi"]),
            "texto": t["complemento_despacho"],
        }
    # O 16.1 traz a vigencia publicada pelo INPI -- fonte melhor que o calculo do art. 40.
    v = [d for d in est["despachos"] if str(d.get("codigo_despacho")) == "16.1"
         and not d.get("anulado_em")]
    if v:
        r["vigencia_publicada_16_1"] = v[-1]["complemento_despacho"]
        r["nota_vigencia"] = (
            "O despacho 16.1 publica a vigencia; prefira-o ao 'fim_vigencia_calculado'."
        )
    return r


# Prazo de recurso: art. 212 da LPI, 60 dias da publicacao. Os codigos 100/121, que
# sao os despachos DE recurso, declaram 60 dias em 87-99% das ocorrencias -- uma das
# poucas constantes confiaveis da tabela de despachos.
DIAS_RECURSO = 60
# Art. 33: requerimento de exame em 36 meses do deposito. Nao requerido, o pedido e
# arquivado -- gera o despacho 11.1, o 11o codigo mais frequente da base (156.260).
MESES_EXAME = 36
# Despachos que evidenciam que o exame ja foi requerido ou que o pedido ja passou dele.
CODIGOS_EXAME_REQUERIDO = {
    "6.1", "6.6", "6.6.1", "6.7", "6.20", "6.21", "6.23", "7.1",
    "9.1", "9.2", "16.1", "11.2",
}
CODIGOS_EXIGENCIA = {"2.5", "6.1", "6.6", "6.7", "6.20", "6.21", "7.1"}


def _prazos_de(est: dict, hoje: date, tipos: set[str], quantas: int = 4) -> list[dict]:
    """Todos os prazos projetaveis de um processo. Nao consulta o banco."""
    num, dep = est["numero_inpi"], est["data_deposito"]
    if not dep:
        return []
    saida: list[dict] = []
    vivos = [d for d in est["despachos"] if not d.get("anulado_em")]
    encerrado = est["encerrado_em"] is not None

    if "anuidade" in tipos and not encerrado:
        p = anu.projetar(dep, num, hoje, em_aberto=est["anuidades_em_aberto"],
                         complementacao=est["anuidades_complementacao"],
                         quantas_futuras=quantas)
        for j in p.get("anuidades", []):
            saida.append({
                "tipo": "anuidade", "numero_inpi": num,
                "descricao": f"{j['anuidade']}a anuidade",
                "prazo": j["fim_complementar"], "status": j["status"],
                "inicio": j["inicio_ordinario"], "fim_ordinario": j["fim_ordinario"],
                "base_legal": "LPI art. 84",
                **({"alerta": j["alerta"]} if "alerta" in j else {}),
                **({"nota": j["nota"]} if "nota" in j else {}),
            })

    if "exame" in tipos and not encerrado:
        ja = any(str(d["codigo_despacho"]) in CODIGOS_EXAME_REQUERIDO for d in vivos)
        if not ja:
            limite = anu._mais_meses(dep, MESES_EXAME)
            if limite >= hoje:
                saida.append({
                    "tipo": "exame", "numero_inpi": num,
                    "descricao": "Requerimento de exame (art. 33)",
                    "prazo": limite.isoformat(),
                    "status": "em_aberto",
                    "base_legal": "LPI art. 33 - 36 meses do deposito",
                    "alerta": "FATAL: nao requerido, o pedido e arquivado (despacho 11.1).",
                    "nota": ("Nenhum despacho de exame foi localizado. Peticao protocolada "
                             "e ainda nao publicada NAO aparece na base -- confira."),
                })

    if "recurso" in tipos:
        for d in vivos:
            if str(d["codigo_despacho"]) not in ("9.2", "11.1", "11.2", "11.5"):
                continue
            limite = d["data_rpi"] + timedelta(days=DIAS_RECURSO)
            if limite >= hoje:
                saida.append({
                    "tipo": "recurso", "numero_inpi": num,
                    "descricao": f"Recurso do despacho {d['codigo_despacho']}",
                    "prazo": limite.isoformat(),
                    "status": "em_aberto",
                    "publicado_em": str(d["data_rpi"]), "rpi": d["numero_rpi"],
                    "base_legal": f"LPI art. 212 - {DIAS_RECURSO} dias da publicacao",
                    "texto_despacho": d["complemento_despacho"],
                })

    if "vigencia" in tipos and not encerrado:
        fim = anu.fim_vigencia(dep, num)
        if fim >= hoje:
            v = [d for d in vivos if str(d["codigo_despacho"]) == "16.1"]
            saida.append({
                "tipo": "vigencia", "numero_inpi": num,
                "descricao": f"Fim de vigencia ({anu.natureza(num)})",
                "prazo": fim.isoformat(), "status": "calculado",
                "base_legal": "LPI art. 40",
                **({"vigencia_publicada_16_1": v[-1]["complemento_despacho"],
                    "nota": "O 16.1 publica a vigencia; prefira-o ao calculo."} if v else {}),
            })

    if "exigencia" in tipos and not encerrado:
        for d in vivos:
            if str(d["codigo_despacho"]) not in CODIGOS_EXIGENCIA:
                continue
            posteriores = [x for x in vivos if x["data_rpi"] > d["data_rpi"]]
            if posteriores:
                continue  # houve movimentacao depois; provavelmente respondida
            saida.append({
                "tipo": "exigencia", "numero_inpi": num,
                "descricao": f"Exigencia {d['codigo_despacho']} sem movimentacao posterior",
                "prazo": None, "status": "conferir_se_respondida",
                "publicado_em": str(d["data_rpi"]), "rpi": d["numero_rpi"],
                "dias_citados_no_texto": _prazo_declarado(d["complemento_despacho"]),
                "texto_despacho": d["complemento_despacho"],
                "nota": ("NAO afirma que esta sem resposta: peticao protocolada e ainda nao "
                         "publicada nao aparece na base. E lista de conferencia."),
            })

    return saida


@mcp.tool()
def inpi_prazos_carteira(
    titular: str | None = None,
    procurador: str | None = None,
    numeros: list[str] | None = None,
    de: str | None = None,
    ate: str | None = None,
    tipos: list[str] | None = None,
    limite_resultados: int = 500,
) -> dict:
    """PROJETA os prazos de uma carteira inteira numa janela de datas.

    USE QUANDO: perguntarem "quantas anuidades a Petrobras paga em julho de 2026",
    "o que vence na nossa carteira no proximo trimestre", "quais casos vencem o prazo
    de exame".

    Filtre por 'procurador' (a carteira do escritorio), 'titular' (o cliente) ou
    'numeros'. A janela 'de'/'ate' filtra pela data do prazo.

    Tipos disponiveis (padrao: todos menos 'exigencia'):
      anuidade  - art. 84, projetada da data de deposito
      exame     - art. 33, 36 meses do deposito. FATAL.
      recurso   - art. 212, 60 dias de indeferimento ou arquivamento
      vigencia  - art. 40, 20 anos (invencao) ou 15 (modelo de utilidade)
      exigencia - exigencias sem movimentacao posterior (lista de CONFERENCIA)

    ATENCAO: e PROJECAO, nao fatura. A base registra consequencia, nao vencimento
    futuro; pagamento em dia nao gera despacho. Use como lista de conferencia contra
    o controle de prazos do escritorio, nunca como substituto dele.
    """
    if not (titular or procurador or numeros):
        return {"erro": True, "mensagem": "Informe 'titular', 'procurador' ou 'numeros'."}
    try:
        d_ini = date.fromisoformat(de) if de else date.today()
        d_fim = date.fromisoformat(ate) if ate else anu._mais_meses(d_ini, 12)
    except ValueError as e:
        return {"erro": True, "mensagem": f"Data invalida (use AAAA-MM-DD): {e}"}

    escolhidos = set(tipos) if tipos else {"anuidade", "exame", "recurso", "vigencia"}
    validos = {"anuidade", "exame", "recurso", "vigencia", "exigencia"}
    if not escolhidos <= validos:
        return {"erro": True, "mensagem": f"tipos deve ser subconjunto de {sorted(validos)}"}

    alvos = [normaliza_numero(n) for n in numeros] if numeros else None
    estados, total = _carregar_lote(numeros=alvos, titular=titular, procurador=procurador)

    prazos, encerrados, sem_base = [], 0, 0
    for est in estados.values():
        if not est["data_deposito"]:
            sem_base += 1
            continue
        if est["encerrado_em"]:
            encerrados += 1
        for p in _prazos_de(est, d_ini, escolhidos):
            if p["prazo"] is None:
                prazos.append(p)
                continue
            # Anuidade tem JANELA (inicio ordinario -> fim complementar), nao data
            # unica. Filtrar so pelo fim escondia as que ABREM dentro do periodo --
            # exatamente as que ainda dao para pagar sem retribuicao adicional.
            # Medido na Tecnored: 8 respostas em vez de 22.
            ini = p.get("inicio")
            if ini:
                if ini <= d_fim.isoformat() and p["prazo"] >= d_ini.isoformat():
                    prazos.append(p)
            elif d_ini.isoformat() <= p["prazo"] <= d_fim.isoformat():
                prazos.append(p)

    # Ordena pela data em que a acao COMECA a ser possivel (inicio ordinario), nao
    # pelo fim: e a ordem em que o operador vai trabalhar.
    prazos.sort(key=lambda x: (x.get("inicio") or x["prazo"] or "9999",
                               x["prazo"] or "9999", x["numero_inpi"]))
    truncado = len(prazos) > limite_resultados
    por_tipo: dict[str, int] = {}
    for p in prazos:
        por_tipo[p["tipo"]] = por_tipo.get(p["tipo"], 0) + 1

    return {
        "criterio": {
            "titular": titular, "procurador": procurador,
            "casos_no_criterio": total, "casos_avaliados": len(estados),
            "de": d_ini.isoformat(), "ate": d_fim.isoformat(),
            "tipos": sorted(escolhidos),
        },
        "resumo": {
            "prazos_encontrados": len(prazos),
            "por_tipo": por_tipo,
            "casos_encerrados": encerrados,
            "casos_sem_data_de_deposito": sem_base,
        },
        "truncado": truncado,
        **({"aviso_truncamento":
            f"Exibindo {limite_resultados} de {len(prazos)} prazos. Aumente "
            "'limite_resultados' ou estreite a janela para ver o resto."} if truncado else {}),
        "prazos": prazos[:limite_resultados],
        "aviso": (
            "PROJECAO, nao fatura. Nenhum destes vencimentos foi publicado pelo INPI -- "
            "sao calculados a partir da data de deposito e das regras citadas em "
            "'base_legal'. A base nao sabe o que ja foi pago nem o que foi protocolado "
            "sem publicacao. Confira contra o controle de prazos do escritorio."
        ),
    }


@mcp.tool()
def inpi_relatorio_prazos_pdf(
    titular: str | None = None,
    procurador: str | None = None,
    numeros: list[str] | None = None,
    de: str | None = None,
    ate: str | None = None,
    saida: str | None = None,
) -> dict:
    """Gera PDF de prazos com resumo executivo e identidade Clarke Modet."""
    return gerar_prazos_pdf(
        titular=titular,
        escritorio=procurador,
        numeros=numeros,
        de=de,
        ate=ate,
        saida=saida,
    )


@mcp.tool()
def inpi_regra_jurisdicao(jurisdicao: str) -> dict:
    """Regra de anuidade/manutencao e prazo de fase nacional de uma jurisdicao.

    USE QUANDO: for orientar sobre manutencao no exterior (US, EP, CN, JP, ...).

    So o Brasil devolve datas projetadas -- e a unica regra com evidencia nesta base
    (calibrada contra 285.409 despachos). As demais sao transcricao de legislacao,
    sem verificacao: devolvem a REGRA e a base legal para conversar com o associado
    local, e nao datas. Para liberar uma jurisdicao, preencha 'revisado_por' em
    inpi/referencias/anuidades-por-jurisdicao.csv.
    """
    return jur.descrever(jurisdicao)


@mcp.tool()
def inpi_prazo_fase_nacional(data_prioridade: str,
                             jurisdicoes: list[str] | None = None) -> dict:
    """Prazos de entrada em fase nacional do PCT, contados da prioridade mais antiga.

    USE QUANDO: houver um PCT e for preciso decidir onde entrar. Devolve as datas
    ordenadas, da mais proxima para a mais distante.

    Este marco (30 ou 31 meses) vem do proprio PCT e e uniforme, por isso projetamos
    mesmo sem revisao por jurisdicao. Ainda assim confirme com o associado: perder
    este prazo e irreversivel na maioria dos paises.

    Args:
        data_prioridade: 'AAAA-MM-DD' da prioridade mais antiga.
        jurisdicoes: siglas (ex.: ['US','EP','CN']). Omita para todas as da tabela.
    """
    return jur.fase_nacional(date.fromisoformat(data_prioridade), jurisdicoes)


# ---------------------------------------------------------------------------
# Vigilancia de carteira
# ---------------------------------------------------------------------------


@mcp.tool()
def inpi_novidades(desde: str, numeros: list[str] | None = None,
                   titular: str | None = None, procurador: str | None = None) -> dict:
    """O que saiu de novo numa carteira desde uma data.

    USE QUANDO: perguntarem "o que mudou nos nossos casos esta semana" -- e a
    pergunta operacional mais frequente de um escritorio.

    Filtre por 'procurador' (a carteira do escritorio), 'titular' (o cliente) ou
    'numeros'. Marca despachos ANULADOS por publicacao posterior: no PI0803071 da
    Petrobras, a extincao por anuidade (21.6, RPI 2897) foi anulada sete dias depois
    pelo 21.8. Quem lesse so o primeiro agiria sobre ato que deixou de existir.

    Args:
        desde: 'AAAA-MM-DD'. Use a data da ultima conferencia.
        numeros: processos especificos, em qualquer formato.
        titular: nome do depositante.
        procurador: nome do escritorio.
    """
    if not (numeros or titular or procurador):
        return {"erro": True, "mensagem": "Informe 'numeros', 'titular' ou 'procurador'."}
    try:
        d_desde = date.fromisoformat(desde)
    except ValueError:
        return {
            "erro": True,
            "mensagem": f"'desde' deve ser AAAA-MM-DD; recebido {desde!r}. "
                        "Formato errado devolveria zero novidades sem erro.",
        }

    alvos = [normaliza_numero(n) for n in numeros] if numeros else None
    # 'desde' entra no SQL. Seguro para _marca_anulacoes: a anulacao e sempre
    # posterior ao despacho que ela anula, entao a janela nunca corta o anulador
    # deixando o anulado.
    estados, total = _carregar_lote(
        numeros=alvos, titular=titular, procurador=procurador, desde=d_desde.isoformat()
    )

    novidades = []
    for est in estados.values():
        for d in est["despachos"]:
            d["dias_citados_no_texto"] = _prazo_declarado(d.get("complemento_despacho"))
            d["terminal"] = str(d["codigo_despacho"]) in anu.CODIGOS_TERMINAIS
            novidades.append(d)
    novidades.sort(key=lambda x: (str(x["data_rpi"]), x["numero_inpi"]))

    cob = _linhas("SELECT max(data_rpi) u, max(numero_rpi) n FROM despachos")[0]
    anulados = sum(1 for d in novidades if d.get("anulado_em"))
    return {
        "desde": d_desde.isoformat(),
        "criterio": {"titular": titular, "procurador": procurador,
                     "casos_no_criterio": total},
        "novidades": len(novidades),
        "despachos_anulados_no_periodo": anulados,
        "cobertura_da_base": {"ultima_rpi": str(cob["u"]), "numero": cob["n"]},
        "resultados": novidades,
        "aviso": (
            f"A base vai ate a RPI {cob['n']} de {cob['u']}. Nada posterior a isso "
            "aparece aqui -- reingira antes de concluir que nao houve movimentacao. "
            "Confira 'anulado_em': despacho anulado por publicacao posterior nao produz "
            "efeito, e so o despacho seguinte revela isso."
        ),
    }

