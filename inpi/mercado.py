"""Inteligencia de mercado e escritorios: carteira, ranking, prospeccao, conflitos.

Extraido de inpi_mcp.py na modularizacao da Fase 0. Logica e docstrings de tool
inalteradas -- so mudou o arquivo que as contem.
"""

from __future__ import annotations

from inpi import escritorios as esc
from inpi.consulta import _linhas, aviso_lag_publicacao
from inpi.mcp_app import mcp
from inpi.prazos import _carregar_lote

# ---------------------------------------------------------------------------
# Carteira, mercado e prospeccao
# ---------------------------------------------------------------------------

_AVISO_PESSOAL = (
    "Esta lista contem PESSOA FISICA. O INPI ja publica o CPF mascarado, mas nome e "
    "endereco sao dado pessoal: uso comercial exige base legal propria (LGPD art. 7o). "
    "Ver docs/lgpd.md. Pessoa juridica nao tem essa restricao."
)


def _chave_escritorio(nome: str) -> str:
    """Resolve o nome digitado para a chave canonica de agrupamento."""
    return esc.normalizar(nome)


def _sem_acento_upper(s: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return " ".join(t.split())


def _composicao(chave: str, grafias: list[dict]) -> dict:
    """Decompoe a carteira de um escritorio em 'firma' (grafias que trazem o nome da
    banca) e 'agentes_afiliados' (nome pessoal de procurador dobrado na chave por
    curadoria endossada -- ex.: 'Orlando de Souza' -> Clarke). EXISTE para o total
    nunca chegar opaco ao agente: sem isto ele reporta '44.708 casos' e nao consegue
    dizer que ~18,9 mil vem de dois agentes da casa. `grafias` = [{original, n}]."""
    token = chave.split()[0] if chave else ""
    motivos = esc.apelidos_com_motivo()
    firma_n = 0
    afiliados: dict[str, dict] = {}
    for g in grafias:
        orig_norm = _sem_acento_upper(g["original"])
        n = g["n"]
        motivo = motivos.get(orig_norm, {}).get("observacao", "")
        # Afiliado = grafia SEM o nome da firma E com motivo explicito de afiliacao
        # (ex.: 'agente da casa'). Sem motivo, uma grafia sem o token e so um typo do
        # nome da firma ('CLARK MODET', sem o 'E') -- conta como firma, nao como agente.
        if (token and token in orig_norm) or not motivo:
            firma_n += n
        else:
            slot = afiliados.setdefault(
                orig_norm,
                {"procurador": orig_norm, "processos": 0, "motivo": motivo},
            )
            slot["processos"] += n
    afiliados_ord = sorted(afiliados.values(), key=lambda x: -x["processos"])
    return {
        "firma_processos": firma_n,
        "agentes_afiliados_processos": sum(a["processos"] for a in afiliados_ord),
        "agentes_afiliados": afiliados_ord,
        "nota": (
            "Total = firma + agentes_afiliados. 'agentes_afiliados' sao procuradores "
            "pessoa fisica cujos casos foram atribuidos a banca por curadoria revisada "
            "(coluna 'observacao' do apelidos), NAO erro de agrupamento. Cite a "
            "composicao ao dar o total."
        ) if afiliados_ord else "Carteira so de grafias da propria firma, sem agentes afiliados.",
    }


@mcp.tool()
def inpi_escritorio_resolver(nome: str) -> dict:
    """Mostra em que chave um nome de escritorio cai, e quais grafias ela agrupa.

    USE QUANDO: antes de confiar em qualquer numero de carteira ou de mercado. A base
    tem ~17,5 mil grafias de procurador para ~10 mil escritorios reais -- a Clarke Modet
    sozinha aparece em dezenas de formas. Se a chave errada for usada, todo o resto erra
    junto. O bloco 'composicao' separa as grafias da propria firma dos agentes pessoa
    fisica afiliados (curadoria endossada), para o total nunca chegar opaco.

    ISTO E RESOLUCAO DE IDENTIDADE, NUNCA RESPOSTA DE VOLUME/RANKING/TECNOLOGIA:
    'processos' aqui e o total sob a chave, para CONFERIR a chave -- nao chame esta
    tool para responder "quantos processos", "quem lidera" ou "qual a tecnologia
    dominante"; use inpi_carteira/inpi_producao_escritorio/inpi_mercado para isso.
    """
    chave = _chave_escritorio(nome)
    grafias = _linhas(
        """SELECT e.original, count(DISTINCT p.numero_inpi) n
           FROM escritorios e JOIN procuradores p ON p.procurador = e.original
           WHERE e.chave = ? GROUP BY 1 ORDER BY n DESC""",
        [chave],
    )
    parecidas = _linhas(
        """SELECT DISTINCT chave FROM escritorios
           WHERE chave ILIKE ? AND chave <> ? LIMIT 15""",
        [f"%{chave.split()[0]}%" if chave else "%", chave],
    )
    return {
        "nome_consultado": nome,
        "chave": chave,
        "processos": sum(g["n"] for g in grafias),
        "grafias_agrupadas": len(grafias),
        "grafias": grafias[:30],
        "composicao": _composicao(chave, grafias),
        "chaves_parecidas_nao_agrupadas": [p["chave"] for p in parecidas],
        "nota": (
            "'chaves_parecidas_nao_agrupadas' sao candidatas a erro de digitacao que a "
            "normalizacao nao une (ex.: 'CLARK MODET'). Se alguma for a mesma empresa, "
            "acrescente em inpi/referencias/escritorios-apelidos.csv e reingira."
        ),
    }


# Codigos de despacho relevantes a exigencia, com o rotulo empirico do
# inpi/referencias/prazos-observados.md (indicio no texto, nao tabela oficial).
# 'exigencia' = o INPI EMITIU uma exigencia; 'nao_cumprida'/'desfecho' = o que ele
# publicou depois. NAO existe codigo "exigencia cumprida" -- ver docstring da tool.
_CODIGOS_EXIGENCIA = {
    "6.1": "exigencia tecnica (art. 25) — emitida",
    "2.5": "exigencia formal preliminar (30 dias) — emitida",
    "7.1": "parecer com exigencia (nao atende art. 25) — emitido",
}
_CODIGOS_DESFECHO = {
    "11.2": "arquivado por exigencia NAO cumprida (art. 36 §1o)",
    "9.1": "concedido (desfecho favoravel — exigencias, se houve, foram superadas)",
    "9.2": "indeferido",
    "11.1": "arquivado por exame nao requerido (art. 33)",
}


@mcp.tool()
def inpi_exigencias_escritorio(escritorio: str, ano: int) -> dict:
    """Exigencias PUBLICADAS para os processos de um escritorio num ano, e o desfecho
    que o INPI publicou -- o mais perto que os dados abertos chegam de "exigencias
    cumpridas".

    ⚠️ LEIA ANTES DE RESPONDER: o CUMPRIMENTO de uma exigencia e uma PETICAO (servicos
    206/207 na GRU), protocolada pelo escritorio, que os dados abertos do INPI NAO
    publicam. NAO existe despacho "exigencia cumprida". Logo NAO da para contar
    cumprimentos direto -- quem responder um numero de "exigencias cumpridas" esta
    inventando. O que ESTA base permite, e o que esta tool devolve:
      - exigencias EMITIDAS no ano (codigos 6.1, 2.5, 7.1): o universo que o escritorio
        teve de responder;
      - NAO cumpridas: codigo 11.2 (arquivamento por exigencia nao cumprida) -- estas o
        INPI publica, e sao a unica afirmacao direta sobre cumprimento;
      - desfechos (9.1 concessao, 9.2 indeferimento, 11.1 arquivamento art. 33) como
        contexto.
    PROXY honesto de "cumpridas com sucesso" = exigencias emitidas − arquivadas por nao
    cumprimento (11.2), sempre com a ressalva de que e proxy, nao a contagem de peticoes.

    Args:
        escritorio: nome do escritorio (agrupado pela chave curada).
        ano: ano-calendario da PUBLICACAO do despacho (data_rpi), ex.: 2026.
    """
    chave = _chave_escritorio(escritorio)
    codigos = {**_CODIGOS_EXIGENCIA, **_CODIGOS_DESFECHO}
    linhas = _linhas(
        f"""SELECT d.codigo_despacho AS codigo,
                   count(DISTINCT d.numero_inpi) AS processos
            FROM despachos d
            JOIN procuradores p ON p.numero_inpi = d.numero_inpi
            JOIN escritorios e ON e.original = p.procurador
            WHERE e.chave = ? AND year(d.data_rpi) = ?
              AND d.codigo_despacho IN ({','.join('?' for _ in codigos)})
            GROUP BY 1""",
        [chave, int(ano), *codigos.keys()],
    )
    por_codigo = {l["codigo"]: l["processos"] for l in linhas}
    emitidas = {c: por_codigo.get(c, 0) for c in _CODIGOS_EXIGENCIA}
    desfechos = {c: por_codigo.get(c, 0) for c in _CODIGOS_DESFECHO}
    total_emitidas = sum(emitidas.values())
    nao_cumpridas = desfechos.get("11.2", 0)

    return {
        "escritorio": escritorio,
        "chave": chave,
        "ano": int(ano),
        "exigencias_emitidas": {
            "total": total_emitidas,
            "por_codigo": {c: {"processos": emitidas[c], "descricao": _CODIGOS_EXIGENCIA[c]}
                           for c in _CODIGOS_EXIGENCIA},
        },
        "arquivadas_por_nao_cumprimento": {
            "codigo": "11.2", "processos": nao_cumpridas,
            "descricao": _CODIGOS_DESFECHO["11.2"],
        },
        "desfechos": {c: {"processos": desfechos[c], "descricao": _CODIGOS_DESFECHO[c]}
                      for c in _CODIGOS_DESFECHO},
        "proxy_cumpridas": max(total_emitidas - nao_cumpridas, 0),
        "aviso": (
            "CUMPRIMENTO de exigencia NAO esta nos dados abertos: e peticao (servico "
            "206/207), nao despacho. Nao ha 'exigencia cumprida' para contar. Os numeros "
            "acima sao o que o INPI PUBLICOU -- exigencias emitidas e arquivamentos por "
            "nao cumprimento (11.2). 'proxy_cumpridas' = emitidas − nao cumpridas e "
            "APROXIMACAO grosseira (ignora exigencias do ano ainda em aberto e desfecho "
            "publicado em outro ano); trate como ordem de grandeza, nunca como a conta do "
            "INPI. Codigos vem de inpi/referencias/prazos-observados.md (indicio empirico, "
            "nao tabela oficial de codigos)."
        ),
    }


@mcp.tool()
def inpi_carteira(escritorio: str, cliente: str | None = None,
                  apenas_vivos: bool = True, limite: int = 200) -> dict:
    """Carteira de um escritorio, opcionalmente filtrada por cliente.

    USE QUANDO: perguntarem "quais casos temos", "quais casos do cliente X",
    "nossa carteira em determinada area" -- ou seja, quando precisar da LISTA de
    processos, nao so a contagem.

    Agrupa as grafias do nome automaticamente. Confira com inpi_escritorio_resolver
    se o numero parecer estranho.

    ⚠️ 'casos' E LISTA TRUNCADA em 'limite' (padrao 200): 'total' e o total real, mas
    NUNCA conte len(casos) nem itere 'casos' para responder "quantos processos" ou
    fazer ranking/agregacao -- para isso, use inpi_producao_escritorio (GROUP BY sobre
    a base inteira, sem truncar). Contar a lista truncada e o erro mais direto de
    subestimar um numero que este servidor pode gerar.
    """
    chave = _chave_escritorio(escritorio)
    params: list = [chave]
    filtro_cli = ""
    if cliente:
        # Pela chave canonica, nao pelo texto: senao "Petrobras" perde os processos
        # gravados como "PETROLEO BRASILEIRO S/A" sem a palavra, e vice-versa.
        filtro_cli = """ AND dp.depositante IN (
              SELECT t2.original FROM titulares t2 WHERE t2.chave IN (
                SELECT t3.chave FROM titulares t3 WHERE t3.original ILIKE ?))"""
        params.append(f"%{cliente.strip()}%")

    linhas = _linhas(
        f"""WITH alvo AS (
              SELECT DISTINCT p.numero_inpi
              FROM procuradores p JOIN escritorios e ON e.original = p.procurador
              WHERE e.chave = ?
            )
            SELECT a.numero_inpi,
                   any_value(dp.depositante) titular,
                   any_value(c.titulo) titulo,
                   any_value(b.data_deposito) data_deposito,
                   max(d.data_rpi) ultimo_despacho,
                   count(DISTINCT d.codigo_despacho) n_despachos
            FROM alvo a
            LEFT JOIN depositantes dp USING (numero_inpi)
            LEFT JOIN conteudo c USING (numero_inpi)
            LEFT JOIN biblio b USING (numero_inpi)
            LEFT JOIN despachos d USING (numero_inpi)
            WHERE 1=1{filtro_cli}
            GROUP BY a.numero_inpi
            ORDER BY ultimo_despacho DESC NULLS LAST""",
        params,
    )

    if apenas_vivos:
        estados, _ = _carregar_lote(numeros=[l["numero_inpi"] for l in linhas][:5000])
        linhas = [
            l for l in linhas
            if not (estados.get(l["numero_inpi"], {}).get("encerrado_em"))
        ]

    grafias = _linhas(
        """SELECT e.original, count(DISTINCT p.numero_inpi) n
           FROM escritorios e JOIN procuradores p ON p.procurador = e.original
           WHERE e.chave = ? GROUP BY 1""",
        [chave],
    )
    return {
        "escritorio": escritorio,
        "chave": chave,
        "cliente": cliente,
        "apenas_vivos": apenas_vivos,
        "total": len(linhas),
        "truncado": len(linhas) > limite,
        "casos": linhas[:limite],
        # Composicao da CHAVE inteira (antes de filtrar por cliente/apenas_vivos):
        # explica de que a carteira do escritorio e feita -- firma vs agentes
        # pessoa fisica afiliados. 'total' acima pode estar filtrado; isto e o contexto.
        "composicao_da_chave": _composicao(chave, grafias),
    }


@mcp.tool()
def inpi_producao_escritorio(escritorio: str, ano: int | None = None,
                             agrupar_por: str = "cliente", top: int = 20) -> dict:
    """Producao agregada de um escritorio sobre a base INTEIRA (GROUP BY, nunca lista
    truncada) -- "quantos depositos", "maior cliente", "quantos da Petrobras", "foco
    tecnologico por ano".

    USE QUANDO: a pergunta for de CONTAGEM/RANKING/TENDENCIA, nao de lista de
    processos -- para lista, use inpi_carteira. NUNCA responda essas perguntas
    contando 'casos' de inpi_carteira: aquela lista e truncada por design, esta tool
    agrega sobre a base inteira.

    'serie_por_ano' vem SEMPRE junto (depositos por ano, contexto obrigatorio de
    qualquer numero de volume), com 'aviso_lag_publicacao': anos recentes aparecem
    baixos por SIGILO do pedido ainda nao vencido (art. 30 LPI), nao por queda real de
    atividade. Auditado no plano de refino 2026-08: a Clarke Modet teve 1.918
    depositos publicados em 2023 e so 4 em 2026 nesta base -- 2026 e o dado PUBLICADO
    correto ate a data de corte, nao uma carteira truncada nem uma queda de atividade;
    o agente NAO deve inventar essa segunda explicacao.

    Args:
        escritorio: nome do escritorio (agrupado pela chave curada, como em
            inpi_carteira/inpi_escritorio_resolver).
        ano: filtra 'ranking_clientes' ou 'foco_tecnologico_por_ano' a um
            ano-calendario de DEPOSITO. Omita para ver o historico inteiro (menos
            sensivel ao lag, porque soma anos maduros e recentes juntos).
        agrupar_por: 'cliente' (ranking_clientes, quem mais depositou) ou 'ipc'
            (foco_tecnologico_por_ano, top subclasses IPC POR ANO -- compare anos
            maduros entre si, ex. 2023 x 2024; nao compare com 2025/2026).
        top: quantos itens no ranking, ou por ano no foco tecnologico (1 a 100).
    """
    if agrupar_por not in ("cliente", "ipc"):
        return {"erro": True, "mensagem": "agrupar_por deve ser 'cliente' ou 'ipc'."}

    chave = _chave_escritorio(escritorio)
    top = max(1, min(top, 100))

    serie = _linhas(
        """WITH alvo AS (
             SELECT DISTINCT p.numero_inpi
             FROM procuradores p JOIN escritorios e ON e.original = p.procurador
             WHERE e.chave = ?
           )
           SELECT CAST(year(b.data_deposito) AS INT) ano,
                  count(DISTINCT a.numero_inpi) depositos
           FROM alvo a JOIN biblio b USING (numero_inpi)
           WHERE b.data_deposito IS NOT NULL
           GROUP BY 1 ORDER BY 1""",
        [chave],
    )

    resultado: dict = {
        "escritorio": escritorio,
        "chave": chave,
        "filtro": {"ano": ano, "agrupar_por": agrupar_por, "top": top},
        "serie_por_ano": serie,
        "aviso_lag_publicacao": aviso_lag_publicacao(),
    }

    if agrupar_por == "cliente":
        resultado["ranking_clientes"] = _linhas(
            """WITH alvo AS (
                 SELECT DISTINCT p.numero_inpi
                 FROM procuradores p JOIN escritorios e ON e.original = p.procurador
                 WHERE e.chave = ?
               )
               SELECT t.chave titular_chave, arg_max(dp.depositante, 1) titular,
                      count(DISTINCT a.numero_inpi) processos
               FROM alvo a
               JOIN depositantes dp USING (numero_inpi)
               JOIN titulares t ON t.original = dp.depositante
               LEFT JOIN biblio b USING (numero_inpi)
               WHERE (CAST(? AS INT) IS NULL OR year(b.data_deposito) = CAST(? AS INT))
               GROUP BY t.chave ORDER BY processos DESC LIMIT ?""",
            [chave, ano, ano, top],
        )
        if ano is not None:
            resultado["nota_ranking"] = (
                f"Filtrado a depositos de {ano}. Se {ano} for o ano corrente ou o "
                "anterior, o numero de cada cliente e PARCIAL por sigilo de "
                "publicacao -- ver 'aviso_lag_publicacao'. Nunca apresente como total "
                "definitivo/final do ano."
            )
    else:
        resultado["foco_tecnologico_por_ano"] = _linhas(
            """WITH alvo AS (
                 SELECT DISTINCT p.numero_inpi
                 FROM procuradores p JOIN escritorios e ON e.original = p.procurador
                 WHERE e.chave = ?
               ), contagem AS (
                 SELECT CAST(year(b.data_deposito) AS INT) ano,
                        substr(i.simbolo, 1, 4) subclasse,
                        count(DISTINCT a.numero_inpi) processos
                 FROM alvo a
                 JOIN ipc i USING (numero_inpi)
                 JOIN biblio b USING (numero_inpi)
                 WHERE i.simbolo IS NOT NULL AND length(i.simbolo) >= 4
                   AND b.data_deposito IS NOT NULL
                   AND (CAST(? AS INT) IS NULL OR year(b.data_deposito) = CAST(? AS INT))
                 GROUP BY 1, 2
               ), ranqueado AS (
                 SELECT ano, subclasse, processos,
                        row_number() OVER (PARTITION BY ano ORDER BY processos DESC) rn
                 FROM contagem
               )
               SELECT ano, subclasse, processos FROM ranqueado
               WHERE rn <= ? ORDER BY ano, processos DESC""",
            [chave, ano, ano, top],
        )
        resultado["nota_foco"] = (
            "Top subclasses IPC POR ANO de deposito (uma tabela ano x subclasse, nao "
            "agregado no periodo inteiro): compare anos MADUROS entre si (ex.: 2023 x "
            "2024). Anos recentes (corrente e anterior) tem poucos processos "
            "publicados ainda e NAO sao comparaveis com anos maduros -- ver "
            "'aviso_lag_publicacao'."
        )

    return resultado


@mcp.tool()
def inpi_mercado(ipc: str | None = None, desde: str | None = None,
                 top: int = 20) -> dict:
    """Ranking de escritorios por volume de processos. Inteligencia competitiva.

    USE QUANDO: perguntarem participacao de mercado, quem lidera uma area tecnica,
    ou como a nossa posicao evoluiu.

    Args:
        ipc: prefixo de classificacao (ex.: 'C08' para polimeros, 'A61K' para farma).
        desde: 'AAAA-MM-DD' sobre a data de deposito.
        top: quantos escritorios listar.
    """
    cond, params = [], []
    if ipc:
        cond.append("i.simbolo LIKE ?")
        params.append(f"{ipc.strip()}%")
    if desde:
        cond.append("b.data_deposito >= ?")
        params.append(desde)
    where = (" WHERE " + " AND ".join(cond)) if cond else ""
    params.append(max(1, min(top, 100)))

    linhas = _linhas(
        f"""SELECT e.chave escritorio, count(DISTINCT p.numero_inpi) processos
            FROM procuradores p
            JOIN escritorios e ON e.original = p.procurador
            LEFT JOIN ipc i USING (numero_inpi)
            LEFT JOIN biblio b USING (numero_inpi)
            {where}
            GROUP BY 1 ORDER BY processos DESC LIMIT ?""",
        params,
    )
    total = sum(l["processos"] for l in linhas)
    for l in linhas:
        l["participacao_no_top"] = round(l["processos"] / total * 100, 1) if total else 0
    resultado = {
        "filtro": {"ipc": ipc, "desde": desde},
        "ranking": linhas,
        "nota": (
            "'participacao_no_top' e sobre a soma dos listados, nao sobre o mercado "
            "inteiro."
        ),
        "aviso_agente_pessoa_fisica": (
            "ATENCAO ao ler este ranking: quando o INPI registra o AGENTE pessoa fisica, "
            "ele o faz NO LUGAR da banca, nao junto. Medido: 'ORLANDO DE SOUZA' tem "
            "11.972 processos e apenas 4 em comum com 'CLARKE MODET'. Logo, bancas cujos "
            "agentes assinam em nome proprio aparecem subestimadas, e nomes de pessoa "
            "fisica aparecem no ranking como se fossem escritorios. Antes de citar "
            "participacao de mercado, verifique com inpi_escritorio_resolver quais nomes "
            "de agente pertencem a cada banca e acrescente-os a "
            "inpi/referencias/escritorios-apelidos.csv."
        ),
    }
    if desde:
        resultado["aviso_lag_publicacao"] = aviso_lag_publicacao()
    return resultado


@mcp.tool()
def inpi_prospeccao(excluir_escritorio: str, ipc: str | None = None,
                    uf: str | None = None, min_pedidos: int = 5,
                    desde: str | None = None, limite: int = 50) -> dict:
    """Titulares com carteira relevante que NAO sao representados por nos.

    USE QUANDO: for prospectar. Lista depositantes ativos, ordenados por volume,
    excluindo quem ja e cliente do escritorio informado.

    Args:
        excluir_escritorio: o nosso nome -- quem ja representamos sai da lista.
        ipc: prefixo de classificacao para focar numa area tecnica.
        uf: sigla do estado do depositante.
        min_pedidos: volume minimo para entrar na lista.
        desde: 'AAAA-MM-DD' sobre a data de deposito, para pegar quem esta ativo.
    """
    chave_nossa = _chave_escritorio(excluir_escritorio)
    cond, params = ["dp.depositante IS NOT NULL"], []
    if ipc:
        cond.append("i.simbolo LIKE ?")
        params.append(f"{ipc.strip()}%")
    if uf:
        cond.append("dp.estado = ?")
        params.append(uf.strip().upper())
    if desde:
        cond.append("b.data_deposito >= ?")
        params.append(desde)
    params += [chave_nossa, min_pedidos]

    params.append(max(1, min(limite, 500)))
    # Agrupa pela chave canonica de titular (raiz de CNPJ, ou nome normalizado).
    # Sem isso a Petrobras aparece 66 vezes e nenhuma estatistica fecha.
    linhas = _linhas(
        f"""SELECT t.chave titular_chave,
                   arg_max(dp.depositante, 1) titular,
                   count(DISTINCT dp.depositante) grafias,
                   any_value(dp.pais) pais, any_value(dp.estado) uf,
                   any_value(dp.tipopessoadepositante) tipo_pessoa,
                   count(DISTINCT dp.numero_inpi) pedidos,
                   max(b.data_deposito) deposito_mais_recente
            FROM depositantes dp
            JOIN titulares t ON t.original = dp.depositante
            LEFT JOIN ipc i USING (numero_inpi)
            LEFT JOIN biblio b USING (numero_inpi)
            WHERE {' AND '.join(cond)}
              AND dp.numero_inpi NOT IN (
                    SELECT p.numero_inpi FROM procuradores p
                    JOIN escritorios e ON e.original = p.procurador
                    WHERE e.chave = ?
              )
            GROUP BY t.chave
            HAVING count(DISTINCT dp.numero_inpi) >= ?
            ORDER BY pedidos DESC LIMIT ?""",
        params,
    )

    tem_pf = any((l.get("tipo_pessoa") or "").lower().startswith("pessoa f") for l in linhas)
    r = {
        "excluido": {"escritorio": excluir_escritorio, "chave": chave_nossa},
        "filtro": {"ipc": ipc, "uf": uf, "min_pedidos": min_pedidos, "desde": desde},
        "encontrados": len(linhas),
        "titulares": linhas,
        "nota": (
            "Ausencia da nossa chave significa que nao ha registro de representacao "
            "NESTA base. O titular pode ser cliente por outra via (marcas, contratos) "
            "ou ter mudado de procurador sem publicacao. Confira antes de abordar."
        ),
    }
    if tem_pf:
        r["aviso_dado_pessoal"] = _AVISO_PESSOAL
    return r


@mcp.tool()
def inpi_serie_mercado(escritorios: list[str] | None = None, ipc: str | None = None,
                       de: str = "1990", ate: str = "2026",
                       granularidade: str = "ano", top: int = 8) -> dict:
    """Evolucao do mercado no tempo: quantos pedidos cada escritorio recebeu por periodo.

    USE QUANDO: perguntarem "qual escritorio mais depositou na historia", "como
    evoluiu nossa participacao", "quem cresceu e quem encolheu".

    Conta pela DATA DE DEPOSITO do pedido, nao pela data do vinculo -- e a leitura
    natural de "depositou em tal ano".

    Args:
        escritorios: nomes a comparar. Omita para pegar os 'top' maiores do periodo.
        ipc: prefixo de classificacao, para recortar por area tecnica.
        de/ate: ano inicial e final.
        granularidade: 'ano' ou 'decada'.
    """
    if granularidade not in ("ano", "decada"):
        return {"erro": True, "mensagem": "granularidade deve ser 'ano' ou 'decada'."}
    periodo = ("year(b.data_deposito)" if granularidade == "ano"
               else "(year(b.data_deposito) // 10) * 10")

    cond = ["b.data_deposito IS NOT NULL",
            f"year(b.data_deposito) BETWEEN {int(de)} AND {int(ate)}"]
    params: list = []
    if ipc:
        cond.append("i.simbolo LIKE ?")
        params.append(f"{ipc.strip()}%")

    chaves = [_chave_escritorio(e) for e in escritorios] if escritorios else None
    if chaves:
        cond.append("e.chave IN (" + ",".join("?" * len(chaves)) + ")")
        params += chaves
    else:
        # sem lista, pega os maiores do proprio periodo
        maiores = _linhas(
            f"""SELECT e.chave FROM procuradores p
                JOIN escritorios e ON e.original = p.procurador
                JOIN biblio b USING (numero_inpi)
                {'LEFT JOIN ipc i USING (numero_inpi)' if ipc else ''}
                WHERE {' AND '.join(cond)}
                GROUP BY 1 ORDER BY count(DISTINCT p.numero_inpi) DESC LIMIT ?""",
            params + [max(1, min(top, 20))],
        )
        chaves = [r["chave"] for r in maiores]
        cond.append("e.chave IN (" + ",".join("?" * len(chaves)) + ")")
        params += chaves

    linhas = _linhas(
        f"""SELECT {periodo} AS periodo, e.chave AS escritorio,
                   count(DISTINCT p.numero_inpi) AS pedidos
            FROM procuradores p
            JOIN escritorios e ON e.original = p.procurador
            JOIN biblio b USING (numero_inpi)
            {'LEFT JOIN ipc i USING (numero_inpi)' if ipc else ''}
            WHERE {' AND '.join(cond)}
            GROUP BY 1, 2 ORDER BY 1, pedidos DESC""",
        params,
    )
    total_hist = _linhas(
        f"""SELECT e.chave AS escritorio, count(DISTINCT p.numero_inpi) AS total
            FROM procuradores p
            JOIN escritorios e ON e.original = p.procurador
            JOIN biblio b USING (numero_inpi)
            {'LEFT JOIN ipc i USING (numero_inpi)' if ipc else ''}
            WHERE {' AND '.join(cond)}
            GROUP BY 1 ORDER BY total DESC""",
        params,
    )
    return {
        "filtro": {"ipc": ipc, "de": de, "ate": ate, "granularidade": granularidade},
        "total_no_periodo": total_hist,
        "serie": linhas,
        "nota": (
            "Contado por data de deposito do pedido. Um pedido antigo que trocou de "
            "procurador aparece no ano do DEPOSITO, sob o escritorio ATUAL -- a base "
            "guarda a representacao vigente, nao a da epoca. Para grandes carteiras "
            "isso desloca volume dos anos antigos para quem representa hoje."
        ),
        "aviso_lag_publicacao": aviso_lag_publicacao(),
    }


@mcp.tool()
def inpi_movimentacao_escritorio(escritorio: str | None = None, de: str = "2000",
                                 ate: str = "2026", dias_carencia: int = 180) -> dict:
    """Quando processos ja existentes passaram a ser representados por um escritorio.

    USE QUANDO: perguntarem "em que epoca houve mais mudanca de escritorio",
    "quantos processos entraram na nossa carteira vindos de outra banca".

    O sinal e o vinculo de procurador que comeca bem depois do deposito: 36% dos
    774.026 vinculos (282.408) sao assim. Antes da carencia, e o procurador
    original do deposito.

    ⚠️ LIMITE QUE NAO TEM COMO CONTORNAR: a base diz para ONDE o processo foi, nunca
    de ONDE veio. Apenas 248 processos em 774.026 registram mais de um escritorio --
    a tabela guarda a representacao vigente, nao a serie historica. Portanto
    "quantos vieram da Dannemann para a Clarke" NAO e respondivel, e nenhum numero
    aqui deve ser lido como tal.

    Args:
        escritorio: nome. Omita para ver o mercado inteiro.
        dias_carencia: margem entre deposito e vinculo para considerar troca.
    """
    cond = [
        "p.data_inicio_procurador IS NOT NULL",
        "b.data_deposito IS NOT NULL",
        f"p.data_inicio_procurador > b.data_deposito + INTERVAL {int(dias_carencia)} DAY",
        f"year(p.data_inicio_procurador) BETWEEN {int(de)} AND {int(ate)}",
    ]
    params: list = []
    if escritorio:
        cond.append("e.chave = ?")
        params.append(_chave_escritorio(escritorio))

    serie = _linhas(
        f"""SELECT year(p.data_inicio_procurador) AS ano,
                   count(DISTINCT p.numero_inpi) AS entradas
            FROM procuradores p
            JOIN escritorios e ON e.original = p.procurador
            JOIN biblio b USING (numero_inpi)
            WHERE {' AND '.join(cond)}
            GROUP BY 1 ORDER BY 1""",
        params,
    )
    top = _linhas(
        f"""SELECT e.chave AS escritorio, count(DISTINCT p.numero_inpi) AS entradas
            FROM procuradores p
            JOIN escritorios e ON e.original = p.procurador
            JOIN biblio b USING (numero_inpi)
            WHERE {' AND '.join(cond)}
            GROUP BY 1 ORDER BY entradas DESC LIMIT 12""",
        params,
    )
    pico = max(serie, key=lambda x: x["entradas"]) if serie else None
    return {
        "filtro": {"escritorio": escritorio, "de": de, "ate": ate,
                   "dias_carencia": dias_carencia},
        "total_entradas": sum(s["entradas"] for s in serie),
        "ano_de_pico": pico,
        "serie_por_ano": serie,
        "por_escritorio": top,
        "limite_conhecido": (
            "Isto conta ENTRADAS, nunca origens. A base nao registra de qual escritorio "
            "o processo veio -- so 248 processos em 774.026 tem mais de um escritorio "
            "gravado. Pergunta do tipo 'quantos vieram da banca X para a banca Y' nao "
            "tem resposta nesta base, em nenhuma agregacao."
        ),
        "nota": (
            f"Considera troca o vinculo iniciado mais de {dias_carencia} dias apos o "
            "deposito. Margem menor pega regularizacao de procuracao do proprio "
            "deposito como se fosse troca; maior perde trocas rapidas."
        ),
    }


@mcp.tool()
def inpi_transferencias_titular(titular: str | None = None, de: str = "2000",
                                ate: str = "2026", min_processos: int = 3,
                                limite: int = 40) -> dict:
    """De-para de TITULARIDADE: quem saiu e quem entrou como dono de uma carteira.

    USE QUANDO: perguntarem sobre aquisicao, fusao, spin-off ou reorganizacao
    societaria; ou para prospectar -- quem acabou de comprar carteira e lead quente.

    Isto existe porque `depositantes` tem data_fim_depositante (126.087 linhas,
    10,5%), o que permite reconstruir a sucessao: o titular com data de fim saiu, o
    sem data de fim ficou. Sao 88.057 processos com troca.

    O que aparece aqui e real e reconhecivel: Motorola Mobility -> Google Technology
    Holdings (aquisicao), Johnson & Johnson Consumer -> Kenvue Brands (spin-off de
    2023), Nippon Steel Sumitomo Metal -> Nippon Steel (mudanca de razao social).

    ⚠️ NAO CONFUNDA com troca de escritorio. Isto e mudanca de DONO da patente, nao
    de quem representa. Troca de procurador nao e rastreavel nesta base -- ver
    inpi_movimentacao_escritorio.

    Args:
        titular: filtra por quem saiu OU quem entrou. Omita para o mercado inteiro.
        de/ate: janela sobre a data de saida do titular anterior.
        min_processos: volume minimo do par para entrar na lista.
    """
    cond = [
        "s.df IS NOT NULL",
        "e.di >= s.df - INTERVAL 30 DAY",
        "s.org <> e.dst",
        f"year(s.df) BETWEEN {int(de)} AND {int(ate)}",
    ]
    params: list = []
    if titular:
        chave_like = f"%{titular.strip().upper()}%"
        cond.append("(upper(s.org) LIKE ? OR upper(e.dst) LIKE ?)")
        params += [chave_like, chave_like]
    params.append(min_processos)
    params.append(max(1, min(limite, 200)))

    linhas = _linhas(
        f"""WITH x AS (
              SELECT dp.numero_inpi, t.chave, dp.data_inicio_depositante AS di,
                     dp.data_fim_depositante AS df, dp.depositante
              FROM depositantes dp JOIN titulares t ON t.original = dp.depositante
            ),
            saiu AS (SELECT numero_inpi, chave AS org, df,
                            arg_max(depositante, 1) AS org_nome
                     FROM x WHERE df IS NOT NULL GROUP BY 1, 2, 3),
            entrou AS (SELECT numero_inpi, chave AS dst, di,
                              arg_max(depositante, 1) AS dst_nome
                       FROM x WHERE df IS NULL GROUP BY 1, 2, 3)
            SELECT s.org, any_value(s.org_nome) AS org_nome,
                   e.dst, any_value(e.dst_nome) AS dst_nome,
                   count(*) AS processos,
                   min(s.df) AS primeira_transferencia,
                   max(s.df) AS ultima_transferencia
            FROM saiu s JOIN entrou e USING (numero_inpi)
            WHERE {' AND '.join(cond)}
            GROUP BY s.org, e.dst
            HAVING count(*) >= ?
            ORDER BY processos DESC LIMIT ?""",
        params,
    )
    return {
        "filtro": {"titular": titular, "de": de, "ate": ate},
        "transferencias": len(linhas),
        "processos_movidos": sum(l["processos"] for l in linhas),
        "resultados": linhas,
        "nota": (
            "Reconstruido por data_fim_depositante. Mudanca de razao social e "
            "aquisicao aparecem iguais aqui -- 'Nippon Steel Sumitomo Metal -> Nippon "
            "Steel' e renomeacao, 'Motorola Mobility -> Google Technology Holdings' e "
            "compra. Distinga pelo nome antes de tratar como operacao de mercado."
        ),
        "uso_comercial": (
            "Titular que acabou de receber carteira e lead: ele tem patente nova para "
            "administrar e pode nao ter escritorio definido no Brasil. Cruze com "
            "inpi_prospeccao para ver se ja e representado por nos."
        ),
    }


@mcp.tool()
def inpi_conflitos_identidade(escritorio: str | None = None, limite: int = 30) -> dict:
    """Onde o NOME e o DOCUMENTO do procurador discordam. Base para revisao humana.

    USE QUANDO: antes de fechar qualquer numero de carteira ou de mercado. Um
    conflito nao resolvido significa que aqueles processos podem estar no escritorio
    errado.

    Nenhum dos dois campos e confiavel sozinho: o nome vem em 17.521 grafias, e o
    documento tem pureza media de 91,4% -- 255 dos 1.073 CNPJs apontam para mais de
    uma banca. Esta tool NAO decide qual lado esta certo; mostra os dois com a
    contagem e os principais clientes de cada, para voce julgar.

    O caso que motivou o desenho: o CNPJ 33163049 tem 181.760 processos com nome
    DANNEMANN e 6.675 com nome CLARKE MODET, com carteiras de clientes
    completamente diferentes e datas sobrepostas de 1981 a 2026.
    """
    cond, params = ["c.confianca = 'conflito'"], []
    if escritorio:
        chave = _chave_escritorio(escritorio)
        cond.append("(c.nome = ? OR c.nome_do_doc = ?)")
        params += [chave, chave]
    params.append(max(1, min(limite, 200)))

    linhas = _linhas(
        f"""SELECT c.nome, c.doc, c.processos, c.nome_do_doc, c.doc_do_nome,
                   c.pureza_doc, c.pureza_nome,
                   round(jaro_winkler_similarity(c.nome, c.nome_do_doc), 3) sim_nome
            FROM identidade_escritorio c
            WHERE {' AND '.join(cond)}
            ORDER BY c.processos DESC LIMIT ?""",
        params,
    )

    # Dois tipos de conflito, e so um exige julgamento.
    # Nome parecido + documento puro = nome truncado ou razao social antiga; o
    # documento manda ('DANIEL' -> 'DANIEL ALT DE DANIEL', 5.556 processos).
    # Nome diferente = disputa real, como Clarke x Dannemann.
    for l in linhas:
        a, b = l["nome"], l["nome_do_doc"] or ""
        # Um nome contido no outro, sobre o mesmo CNPJ, e a mesma banca: nome
        # truncado ('DANIEL' em 'DANIEL ALT DE DANIEL' -- 'ALT DE' e 'alteracao de',
        # razao social anterior), ou sufixo societario ('BEERRE' / 'BEERRE S C').
        # Vale independente da pureza do CNPJ: a substring ja e a evidencia.
        contido = bool(a) and bool(b) and (a in b or b in a)
        l["tipo"] = (
            "resolvivel_pelo_documento"
            if contido or ((l["sim_nome"] or 0) >= 0.85 and (l["pureza_doc"] or 0) >= 0.90)
            else "requer_decisao"
        )
        if l["tipo"] == "resolvivel_pelo_documento":
            l["linha_para_o_csv"] = (
                f'{l["nome"]},{l["nome_do_doc"]},{l["processos"]},,,'
                f'"mesmo CNPJ {l["doc"]} (pureza {l["pureza_doc"]}), '
                f'similaridade {l["sim_nome"]}"'
            )

    # Evidencia: quem sao os clientes, e -- mais importante -- se o conflito ainda
    # importa. Conflito em processo morto nao muda prazo nenhum e nao merece
    # atencao. Medido no caso Clarke x Dannemann: dos 6.675 processos, 4.734 estao
    # encerrados, so 9 tiveram despacho desde 2024 e ZERO tem prazo nos proximos 12
    # meses. A causa e mudanca de escritorio ao longo do tempo -- o INPI atualiza o
    # registro de procurador sem versionar (existe o despacho 15.35, "Atualizacao de
    # procurador"), entao nome e documento podem ser de momentos diferentes.
    for l in linhas:
        viv = _linhas(
            """WITH alvo AS (
                 SELECT DISTINCT p.numero_inpi FROM procuradores p
                 JOIN escritorios e ON e.original = p.procurador
                 WHERE e.chave = ? AND substr(p.cgccpfprocurador, 1, 8) = ?
               ),
               ult AS (SELECT numero_inpi, max(data_rpi) AS ultimo
                       FROM despachos GROUP BY 1)
               SELECT count(*) FILTER (WHERE ultimo >= DATE '2024-01-01') AS recentes
               FROM alvo LEFT JOIN ult USING (numero_inpi)""",
            [l["nome"], l["doc"]],
        )
        ativos = viv[0]["recentes"] if viv else 0
        l["com_despacho_desde_2024"] = ativos
        # Proporcao, nao contagem: 9 processos ativos em 6.675 (0,1%) e ruido, mas 9
        # em 20 seria metade da carteira. O corte binario classificava o caso
        # Clarke x Dannemann como 'revisar' por causa de 9 casos.
        l["proporcao_ativa"] = round(ativos / max(l["processos"], 1), 4)
        l["prioridade"] = (
            "ignorar_historico" if l["proporcao_ativa"] < 0.02 else "revisar"
        )
        l["principais_clientes"] = [
            r["depositante"]
            for r in _linhas(
                """SELECT arg_max(dp.depositante, 1) depositante
                   FROM procuradores p
                   JOIN escritorios e ON e.original = p.procurador
                   JOIN depositantes dp ON dp.numero_inpi = p.numero_inpi
                   WHERE e.chave = ? AND substr(p.cgccpfprocurador, 1, 8) = ?
                   GROUP BY dp.depositante ORDER BY count(*) DESC LIMIT 3""",
                [l["nome"], l["doc"]],
            )
        ]
        l["leitura"] = (
            f"{l['processos']:,} processos gravados com o nome '{l['nome']}' e o "
            f"documento {l['doc']}, que majoritariamente pertence a "
            f"'{l['nome_do_doc']}'. O nome '{l['nome']}' usa majoritariamente o "
            f"documento {l['doc_do_nome']}."
        )

    por_tipo: dict[str, int] = {}
    proc_por_tipo: dict[str, int] = {}
    for l in linhas:
        por_tipo[l["tipo"]] = por_tipo.get(l["tipo"], 0) + 1
        proc_por_tipo[l["tipo"]] = proc_por_tipo.get(l["tipo"], 0) + l["processos"]

    return {
        "filtro": {"escritorio": escritorio},
        "conflitos": len(linhas),
        "por_tipo": por_tipo,
        "processos_por_tipo": proc_por_tipo,
        "resultados": linhas,
        "como_resolver": (
            "'resolvivel_pelo_documento': nome truncado ou razao social antiga sobre um "
            "CNPJ puro -- copie 'linha_para_o_csv' para "
            "inpi/referencias/escritorios-apelidos.csv e reingira. "
            "'requer_decisao': os nomes sao de bancas diferentes; olhe os clientes de "
            "cada lado e decida. Se o nome estiver certo e o documento errado, nao ha "
            "o que fazer -- a chave ja e o nome."
        ),
        "aviso": (
            "Nao ha desempate automatico, de proposito. Mas confira 'prioridade' antes "
            "de gastar tempo: 'ignorar_historico' significa que nenhum processo daquele "
            "conflito teve despacho desde 2024 -- e residuo de mudanca de escritorio "
            "antiga, sem efeito sobre prazo. Concentre-se nos marcados 'revisar'."
        ),
    }


@mcp.tool()
def inpi_candidatos_vinculo(escritorio: str | None = None, min_clientes_comuns: int = 15,
                            cobertura_minima: float = 0.6, limite: int = 40) -> dict:
    """Encontra nomes que provavelmente sao a MESMA banca, para revisao humana.

    USE QUANDO: for conferir um numero de participacao de mercado, ou mapear os
    agentes e as grafias erradas de um concorrente.

    Combina dois sinais independentes:
      - similaridade do nome (Jaro-Winkler)
      - sobreposicao de carteira de clientes

    Como ler o resultado:
      'digitacao'  nome muito parecido E carteira comum. Alta confianca -- normalmente
                   e a mesma banca escrita errada.
      'agente'     nome diferente, carteira comum. Costuma ser advogado ou agente da
                   casa assinando em nome proprio. EXIGE confirmacao: a sobreposicao
                   e fraca por natureza. Medido: Orlando de Souza, confirmado como
                   agente da Clarke Modet, tem apenas 26% de carteira em comum com
                   ela; Flavia Salim Lopes, 36%. Um corte que pegasse os dois traria
                   muito ruido junto.

    Isto NAO decide nada. Devolve candidatos com a evidencia; quem confirma e o
    humano, acrescentando a linha em inpi/referencias/escritorios-apelidos.csv e
    rodando 'python inpi/ingest.py' de novo.
    """
    cond, params = [], []
    if escritorio:
        chave = _chave_escritorio(escritorio)
        cond.append("(p.ea = ? OR p.eb = ?)")
        params += [chave, chave]
    where = (" AND " + " AND ".join(cond)) if cond else ""

    linhas = _linhas(
        f"""WITH carteira AS (
              SELECT e.chave escritorio, t.chave cliente, count(*) n
              FROM procuradores pr
              JOIN escritorios e ON e.original = pr.procurador
              JOIN depositantes dp ON dp.numero_inpi = pr.numero_inpi
              JOIN titulares t ON t.original = dp.depositante
              GROUP BY 1, 2
            ),
            tam AS (
              SELECT escritorio, count(*) clientes, sum(n) processos FROM carteira GROUP BY 1
            ),
            pares AS (
              SELECT a.escritorio ea, b.escritorio eb, count(*) comum
              FROM carteira a JOIN carteira b
                ON a.cliente = b.cliente AND a.escritorio < b.escritorio
              GROUP BY 1, 2 HAVING count(*) >= ?
            )
            SELECT p.ea, ta.processos pa, p.eb, tb.processos pb, p.comum,
                   round(p.comum * 1.0 / least(ta.clientes, tb.clientes), 3) cobertura,
                   round(jaro_winkler_similarity(p.ea, p.eb), 3) similaridade_nome
            FROM pares p
            JOIN tam ta ON ta.escritorio = p.ea
            JOIN tam tb ON tb.escritorio = p.eb
            WHERE p.comum * 1.0 / least(ta.clientes, tb.clientes) >= ?{where}
            ORDER BY similaridade_nome DESC, p.comum DESC
            LIMIT ?""",
        [min_clientes_comuns, cobertura_minima] + params + [max(1, min(limite, 200))],
    )

    for l in linhas:
        maior, menor = ((l["ea"], l["eb"]) if l["pa"] >= l["pb"] else (l["eb"], l["ea"]))
        l["provavel_canonico"] = maior
        l["provavel_variante"] = menor
        l["hipotese"] = "digitacao" if l["similaridade_nome"] >= 0.85 else "agente"
        l["linha_para_o_csv"] = (
            f'{l["provavel_variante"]},{l["provavel_canonico"]},'
            f'{min(l["pa"], l["pb"])},,,"{l["comum"]} clientes em comum '
            f'({l["cobertura"]:.0%}), similaridade {l["similaridade_nome"]}"'
        )

    return {
        "filtro": {"escritorio": escritorio, "min_clientes_comuns": min_clientes_comuns,
                   "cobertura_minima": cobertura_minima},
        "candidatos": len(linhas),
        "por_hipotese": {
            "digitacao": sum(1 for l in linhas if l["hipotese"] == "digitacao"),
            "agente": sum(1 for l in linhas if l["hipotese"] == "agente"),
        },
        "resultados": linhas,
        "como_aplicar": (
            "Confira cada linha. Para as que forem a mesma banca, copie "
            "'linha_para_o_csv' para inpi/referencias/escritorios-apelidos.csv, "
            "preencha revisado_por e revisado_em, e rode 'python inpi/ingest.py'."
        ),
        "aviso": (
            "Candidatos, nao conclusoes. A sobreposicao de carteira NAO detecta agente "
            "de forma confiavel -- agentes da mesma casa atendem clientes diferentes. "
            "Baixar 'cobertura_minima' traz mais agentes verdadeiros e muito mais falso "
            "positivo junto."
        ),
    }


# NAO EXISTE inpi_trocas_de_escritorio, e a ausencia e deliberada.
#
# O plano previa detectar perda e ganho de clientes por procuradores.
# data_inicio_procurador. Medido: apenas 262 processos em 775.370 tem mais de um
# escritorio distinto, e nesses poucos os dois registros trazem a MESMA data -- sao
# a banca e o agente pessoa fisica anotados juntos, nao uma troca ao longo do tempo.
# A tabela guarda a representacao vigente, nao a serie historica. Uma tool aqui
# devolveria sempre zero, o que e pior que nao existir: passa a impressao de que
# nenhum cliente saiu.

