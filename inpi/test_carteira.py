"""Testes da entidade carteira. Sem rede.

O que estes testes protegem e uma coisa so: a carteira nao pode perder caso em
silencio. Linha que nao entra tem que voltar nomeada, e divergencia entre fontes
tem que aparecer em vez de ser sobrescrita pela ultima carga.
"""

import csv

import pytest

from inpi import carteira as ct

CSV_REAL = ct.RAIZ / "referencias" / "carteira-tecnored.csv"


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "BANCO", tmp_path / "carteira.duckdb")


def _casos_do_csv():
    return list(csv.DictReader(CSV_REAL.open(encoding="utf-8")))


def test_normalizar_numero_br_aceita_as_formas_que_circulam():
    alvo = ct.normalizar_numero("BR", "BR 10 2022 010731 2")
    assert alvo == ct.normalizar_numero("BR", "BR-102022010731-A2")
    assert alvo == ct.normalizar_numero("br", "102022010731")


def test_normalizar_numero_estrangeiro_tira_pais_e_kind():
    assert ct.normalizar_numero("EP", "EP-1000000-A1") == "1000000"
    assert ct.normalizar_numero("US", "US 10,123,456 B2") == "10123456"
    # sem digito antes, a letra final e parte do numero, nao kind code
    assert ct.normalizar_numero("ZA", "ZA2019/01234") == "201901234"


def test_le_o_csv_real_sem_ignorar_coluna():
    """As 7 colunas do docketing da Tecnored tem que ser TODAS reconhecidas."""
    r = ct.ler(str(CSV_REAL))
    assert r["formato"] == "csv"
    assert r["colunas_ignoradas"] == []
    assert r["linhas_recusadas"] == []
    assert len(r["casos"]) == len(_casos_do_csv())


def test_csv_xlsx_e_texto_colado_dao_a_mesma_carteira(banco, tmp_path):
    """D6: 'aceitar de qualquer jeito'. Os tres caminhos tem que convergir."""
    from openpyxl import Workbook

    brutos = _casos_do_csv()
    esperado = {(c["pais"].upper(), ct.normalizar_numero(c["pais"], c["numero_oficial"]))
                for c in brutos}

    do_csv = ct.ler(str(CSV_REAL))
    assert {(c["jurisdicao"].upper(),
             ct.normalizar_numero(c["jurisdicao"], c["numero_oficial"]))
            for c in do_csv["casos"]} == esperado

    wb = Workbook()
    ws = wb.active
    ws.append(["Pais", "Numero oficial", "Data de deposito"])
    for c in brutos:
        ws.append([c["pais"], c["numero_oficial"], c["data_base"] or None])
    xlsx = tmp_path / "carteira.xlsx"
    wb.save(xlsx)
    do_xlsx = ct.ler(str(xlsx))
    assert do_xlsx["formato"] == "xlsx"
    assert {(c["jurisdicao"].upper(),
             ct.normalizar_numero(c["jurisdicao"], c["numero_oficial"]))
            for c in do_xlsx["casos"]} == esperado

    colado = "\n".join(f"{c['pais']} {c['numero_oficial']}" for c in brutos)
    do_texto = ct.ler(colado)
    assert do_texto["formato"] == "texto"
    assert do_texto["linhas_recusadas"] == []
    assert {(c["jurisdicao"].upper(),
             ct.normalizar_numero(c["jurisdicao"], c["numero_oficial"]))
            for c in do_texto["casos"]} == esperado


def test_ingestao_nao_engole_coluna_nem_linha(banco, tmp_path):
    arq = tmp_path / "lista.csv"
    arq.write_text(
        "pais,numero_oficial,mandante_do_caso\n"
        "BE,EP1234567,Fulano\n"
        ",,\n"
        "sem pais nenhum,,x\n",
        encoding="utf-8",
    )
    r = ct.ingerir(str(arq), cliente="acme")
    assert r["casos_gravados"] == 1
    assert "mandante_do_caso" in r["colunas_ignoradas"]
    assert any("sem pais nenhum" in l for l in r["linhas_recusadas"])
    assert r["aviso"]


def test_tabela_reconhecida_por_qualquer_coluna_do_cabecalho(banco, tmp_path):
    """Olhar so a primeira celula jogava para o parser de texto solto toda planilha
    que comeca por 'Nosso Ref' -- e toda que usa tab como separador."""
    arq = tmp_path / "lista.csv"
    arq.write_text("Nosso Ref\tPais\tNumero\nABC-1\tBE\tEP1234567\n", encoding="utf-8")
    r = ct.ler(str(arq))
    assert r["formato"] == "csv"
    assert r["casos"] == [{"familia": "ABC-1", "jurisdicao": "BE",
                           "numero_oficial": "EP1234567"}]


def test_texto_recusa_linha_sem_numero(banco):
    r = ct.ler("BE EP1234567\nlinha solta sem nada")
    assert len(r["casos"]) == 1
    assert r["linhas_recusadas"] == ["linha solta sem nada"]


def test_conflito_entre_fontes_aparece_em_vez_de_ser_sobrescrito(banco):
    """A ultima carga NAO pode apagar a divergencia -- e ela que o procurador
    precisa ver. Por isso 'fonte' entra na chave primaria."""
    ct.gravar("acme", [{"jurisdicao": "EP", "numero_oficial": "EP-1000000-A1",
                        "data_deposito": "1998-05-20"}], fonte="lista")
    ct.gravar("acme", [{"jurisdicao": "EP", "numero_oficial": "EP1000000",
                        "data_deposito": "1998-06-01"}], fonte="inpadoc")

    r = ct.listar("acme")
    assert r["total"] == 1, "o mesmo caso em duas fontes e UM caso"
    caso = r["casos"][0]
    assert set(caso["fontes"]) == {"lista", "inpadoc"}
    assert caso["conflito"] is True
    # a lista do escritorio e quem manda no valor exibido
    assert str(caso["data_deposito"]) == "1998-05-20"
    assert r["conflitos"][0]["campo"] in ("data_deposito", "data_base")


def test_listar_denuncia_caso_sem_data_base(banco):
    ct.gravar("acme", [{"jurisdicao": "BE", "numero_oficial": "EP7654321"}],
              fonte="lista")
    r = ct.listar("acme")
    assert r["sem_data_base"] == ["EP7654321"]


def _register_falso(monkeypatch, designados, mencao="20181128"):
    from epo import epo_mcp

    monkeypatch.setattr(epo_mcp, "epo_register", lambda ref: {
        "encontrado": True, "estados_designados": designados,
        "mencao_de_concessao": mencao, "situacao": "The patent has been granted",
    })


def test_validacao_ep_projeta_o_prazo_do_art_65(banco, monkeypatch):
    """A mencao de concessao vem do Register e nao depende de publicacao nacional --
    e por isso o unico prazo dos paises de Londres que da para projetar."""
    _register_falso(monkeypatch, ["BE", "FR", "GB", "GR", "IE", "IT", "LU", "NL", "SE"])
    ct.gravar("acme", [{"jurisdicao": "BE", "numero_oficial": "3088824",
                        "familia": "EP14874476", "tipo": "EP-nac"}], fonte="lista")
    v = ct.validacoes_ep("acme")["validacoes"][0]
    assert v["mencao_de_concessao"] == "2018-11-28"
    assert v["prazo_de_validacao"] == "2019-02-28"
    assert v["confianca"] == "estimado"


def test_validacao_ep_acusa_estado_de_londres_sem_registro(banco, monkeypatch):
    """A lacuna acionavel: designado em estado de Londres, sem registro na carteira.
    Se houve validacao la, NENHUMA fonte publica mostra."""
    _register_falso(monkeypatch, ["BE", "FR", "GB", "GR", "IE", "DE", "ES"])
    for j in ("BE", "FR", "GB"):
        ct.gravar("acme", [{"jurisdicao": j, "numero_oficial": "3088824",
                            "familia": "EP14874476", "tipo": "EP-nac"}], fonte="lista")
    v = ct.validacoes_ep("acme")["validacoes"][0]
    assert v["estados_de_londres_sem_registro"] == ["GR", "IE"]
    assert "GR, IE" in v["pergunta_para_o_associado"]


def test_validacao_ep_nao_transforma_designados_em_carteira(banco, monkeypatch):
    """Regressao de desenho: o deposito designa ~39 estados de uma vez. Contar
    designado como caso inventaria 39 casos por patente. So os 9 de Londres, e so
    os que faltam, viram pergunta -- e nenhum deles vira caso."""
    _register_falso(monkeypatch, ["AL", "AT", "BE", "BG", "CH", "CY", "CZ", "DE", "DK",
                                  "EE", "ES", "FI", "FR", "GB", "GR", "IE", "IT", "NL"])
    ct.gravar("acme", [{"jurisdicao": "BE", "numero_oficial": "3088824",
                        "familia": "EP14874476", "tipo": "EP-nac"}], fonte="lista")
    v = ct.validacoes_ep("acme")["validacoes"][0]
    # 18 designados; destes, 7 sao de Londres; BE ja esta na carteira -> 6 perguntas
    assert v["estados_de_londres_sem_registro"] == ["FR", "GB", "GR", "IE", "IT", "NL"]
    assert ct.listar("acme")["total"] == 1, "a carteira continua com um caso so"


def test_validacao_ep_nao_confunde_numero_estrangeiro_com_publicacao_ep(banco, monkeypatch):
    """Regressao: numero canadense tambem tem 7 digitos. Aceitar qualquer numero de
    7 digitos fazia o Register ser consultado com CA 3282304 como se fosse um EP."""
    _register_falso(monkeypatch, ["BE", "FR"])
    ct.gravar("acme", [{"jurisdicao": "CA", "numero_oficial": "3282304",
                        "familia": "EP23921603", "tipo": "nacional"}], fonte="lista")
    r = ct.validacoes_ep("acme")
    assert r["consultadas"] == 0
    assert r["sem_numero_de_publicacao_ep"] == ["EP23921603"]


def test_validacao_ep_nao_inventa_lacuna_em_ep_ainda_em_exame(banco, monkeypatch):
    """Sem mencao de concessao nao houve o que validar. Apontar 9 estados de Londres
    ali seria criar duvida sobre ato que ainda nao podia ter acontecido."""
    _register_falso(monkeypatch, list(ct.LONDRES), mencao=None)
    ct.gravar("acme", [{"jurisdicao": "BE", "numero_oficial": "3999999",
                        "familia": "EP24909250", "tipo": "EP-nac"}], fonte="lista")
    v = ct.validacoes_ep("acme")["validacoes"][0]
    assert v["prazo_de_validacao"] is None
    assert v["estados_de_londres_sem_registro"] == []


def test_panorama_sempre_entrega_lacunas(banco, monkeypatch):
    """A secao de lacunas nao pode faltar: e ela que impede ler um quadro incompleto
    como completo."""
    ct.gravar("acme", [
        {"jurisdicao": "CA", "numero_oficial": "2970818", "data_base": "2015-11-09"},
        {"jurisdicao": "XX", "numero_oficial": "999", "data_base": "2015-11-09"},
        {"jurisdicao": "BE", "numero_oficial": "3088824"},
    ], fonte="lista")
    r = ct.panorama("acme", de="2026-01-01", ate="2026-12-31",
                    incluir_validacao_ep=False)
    lac = r["lacunas"]
    # BE nao esta na tabela por engano nenhum: BE, FR, GR, IE, IT, LU, NL e SE nao
    # tem linha nacional em anuidades-por-jurisdicao.csv. Um caso desses so e
    # projetado quando vem marcado tipo='EP-nac', que roteia para a regra EP-NAC.
    assert lac["jurisdicoes_fora_da_tabela_de_regras"] == ["BE", "XX"]
    assert "CA" in lac["jurisdicoes_com_regra_nao_revisada"]
    assert lac["casos_sem_data_base"] == ["3088824"]
    assert r["por_confianca"].get("estimado")


def test_panorama_roteia_ep_nac_para_a_regra_de_ep_validado(banco):
    """Sem o roteamento, BE cai no lookup por pais, nao acha regra nacional e a
    validacao europeia inteira some do quadro."""
    ct.gravar("acme", [{"jurisdicao": "BE", "numero_oficial": "3088824",
                        "tipo": "EP-nac", "data_base": "2014-12-22"}], fonte="lista")
    r = ct.panorama("acme", de="2026-01-01", ate="2026-12-31",
                    incluir_validacao_ep=False)
    assert r["lacunas"]["jurisdicoes_fora_da_tabela_de_regras"] == []
    # a 12a venceu em 22/12/2025 e continua DEVIDA dentro da graca; a 13a vence em
    # 22/12/2026. Vencida-mas-pagavel e a mais urgente das duas, nao pode sumir.
    assert [p["descricao"] for p in r["prazos"]] == ["12a anuidade", "13a anuidade"]
    assert r["prazos"][0]["situacao"].startswith("VENCIDA")


def test_fila_de_revisao_prioriza_pelo_peso_na_carteira(banco):
    """Revisar por ordem alfabetica desperdicaria o esforco: numa carteira real de
    59 casos, assinar SO a linha EP-nac converte 30 deles."""
    ct.gravar("acme", [
        {"jurisdicao": "BE", "numero_oficial": "1", "tipo": "EP-nac"},
        {"jurisdicao": "FR", "numero_oficial": "1", "tipo": "EP-nac"},
        {"jurisdicao": "IT", "numero_oficial": "1", "tipo": "EP-nac"},
        {"jurisdicao": "CA", "numero_oficial": "2970818"},
    ], fonte="lista")
    r = ct.a_revisar("acme")
    fila = [(f["jurisdicao"], f["casos_na_carteira"]) for f in r["a_revisar"]]
    assert fila[0] == ("EP-NAC", 3), "caso EP-nac pesa na regra EP-NAC, nao na do pais"
    assert ("CA", 1) in fila
    assert r["ja_assinadas"] == ["BR"], "so o Brasil esta calibrado hoje"
    assert r["a_revisar"][0]["confirmar"], "todo item traz o que perguntar"


def _legal_falso(monkeypatch, pagos, caducados=(), atos=()):
    from epo import epo_mcp

    por_pais = {p: {"caducou": False, "taxa_paga": True, "atos": 1,
                    "ultimo_evento": "2026-01-01"} for p in pagos}
    for p in caducados:
        por_pais[p] = {"caducou": True, "taxa_paga": False, "atos": 1,
                       "ultimo_evento": "2026-01-01"}
    for p in atos:
        por_pais.setdefault(p, {"caducou": False, "taxa_paga": False, "atos": 2,
                                "ultimo_evento": "2026-01-01"})
    monkeypatch.setattr(epo_mcp, "epo_status_legal", lambda ref, **kw: {
        "encontrado": True, "por_pais": por_pais,
        "taxa_nacional_paga_em": sorted(pagos), "caducado_em": sorted(caducados)})
    monkeypatch.setattr(epo_mcp, "epo_register", lambda ref: {
        "encontrado": True, "data_deposito": "20141222",
        "mencao_de_concessao": "20181128", "estados_designados": list(ct.LONDRES)})


def test_descobre_validacao_nos_paises_do_acordo_de_londres(banco, monkeypatch):
    """Derruba a premissa de carteira_manual.py: a validacao em BE/FR/GB/... nao gera
    publicacao nacional e some da familia INPADOC -- mas o escritorio nacional reporta
    o pagamento da anuidade ao EPO, e isso aparece no status legal.

    Conferido ao vivo na familia EP14874476: dos 15 estados europeus do docketing, o
    status legal achou os 15, os 9 de Londres inclusive."""
    _legal_falso(monkeypatch, pagos=list(ct.LONDRES) + ["PT"])
    ct.gravar("acme", [{"jurisdicao": "BE", "numero_oficial": "3088824",
                        "familia": "EP14874476", "tipo": "EP-nac"}], fonte="lista")
    d = ct.descobrir_validacoes("acme")
    assert set(d["validacoes_por_familia"]["EP14874476"]) >= set(ct.LONDRES)
    achados = {c["jurisdicao"] for c in ct.listar("acme")["casos"]}
    assert achados >= set(ct.LONDRES), "os 9 estados de Londres entram na carteira"


def test_validacao_descoberta_casa_com_a_da_lista_mesmo_com_outro_numero(banco, monkeypatch):
    """A lista numera pelo PEDIDO europeu (ES 15868739) e o INPADOC pela PUBLICACAO
    (ES 3235912). Casar so pelo numero duplicava a mesma validacao."""
    _legal_falso(monkeypatch, pagos=["ES"])
    # como no docketing real: BE pelo numero da publicacao, ES pelo do pedido
    ct.gravar("acme", [
        {"jurisdicao": "BE", "numero_oficial": "3088824",
         "familia": "EP14874476", "tipo": "EP-nac"},
        {"jurisdicao": "ES", "numero_oficial": "14874476",
         "familia": "EP14874476", "tipo": "EP-nac"},
    ], fonte="lista")
    ct.descobrir_validacoes("acme")
    r = ct.listar("acme")
    es = [c for c in r["casos"] if c["jurisdicao"] == "ES"]
    assert len(es) == 1, "mesma validacao, dois numeros, UM caso"
    assert set(es[0]["fontes"]) == {"lista", "inpadoc-legal"}


def test_caducado_nao_entra_no_quadro_de_prazos(banco, monkeypatch):
    """PG25 e o escritorio nacional comunicando a extincao. Projetar anuidade ali
    manda pagar o que nao existe mais."""
    _legal_falso(monkeypatch, pagos=["FR"], caducados=["CH"])
    ct.gravar("acme", [{"jurisdicao": "FR", "numero_oficial": "3088824",
                        "familia": "EP14874476", "tipo": "EP-nac"}], fonte="lista")
    ct.descobrir_validacoes("acme")
    r = ct.panorama("acme", de="2026-01-01", ate="2026-12-31",
                    incluir_validacao_ep=False)
    assert "CH" not in {p["jurisdicao"] for p in r["prazos"]}
    assert "casos_caducados_fora_do_quadro" in r["lacunas"]


def test_data_ambigua_vira_none_em_vez_de_chute():
    assert ct._data("03/04/2026").isoformat() == "2026-04-03"
    assert ct._data("20260403").isoformat() == "2026-04-03"
    assert ct._data("abril de 2026") is None
    assert ct._data("") is None
