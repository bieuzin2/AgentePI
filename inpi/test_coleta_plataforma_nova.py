from __future__ import annotations

from unittest.mock import MagicMock

import httpx

import inpi.coleta_plataforma_nova as mod
from inpi.coleta_plataforma_nova import (
    _extrair_cpc,
    _mapear_anuidade,
    _nao_encontrado,
    coletar_com_fallback_pepi,
    coletar_e_registrar,
)
from inpi.plataforma_nova import PlataformaNovaError


def test_mapear_anuidade_extrai_numero_gru_valor_data_e_situacao():
    # Forma real observada em getListingData (2026-09-04), coluna 'value':
    # [Anuidade, GRU, prazo ordinario, prazo extraordinario, valor, data pagamento, situacao HTML]
    value = [
        "5ª Anuidade", "1234567", "01/06/2026<br>01/09/2026",
        "02/09/2026<br>01/03/2027", "R$ 435,00", "10/05/2026",
        '<div><span style="white-space: nowrap;">Averbada</span></div>',
    ]
    item = _mapear_anuidade(value)
    assert item == {
        "numero": "5", "status": "Averbada", "gru": "1234567",
        "valor": "R$ 435,00", "data_pagamento": "10/05/2026",
    }


def test_mapear_anuidade_com_campos_vazios_nao_quebra():
    value = ["7ª Anuidade", "", "01/06/2028<br>01/09/2028",
             "02/09/2028<br>01/03/2029", "", "",
             '<div><span>Indisponível</span></div>']
    item = _mapear_anuidade(value)
    assert item["numero"] == "7"
    assert item["gru"] is None
    assert item["valor"] is None
    assert item["status"] == "Indisponível"


def test_extrair_cpc_pega_campo_inid_52():
    biblio = [
        {"inid": "51", "value": "C08L 5/04"},
        {"inid": "52", "value": "C08L 5/04; C08L 99/00"},
    ]
    assert _extrair_cpc(biblio) == "C08L 5/04; C08L 99/00"


def test_extrair_cpc_ausente_devolve_none():
    assert _extrair_cpc([{"inid": "51", "value": "C08L 5/04"}]) is None


def test_coletar_e_registrar_chama_registrar_com_campos_mapeados(monkeypatch):
    cliente = MagicMock()
    cliente.get_bibliographic_data.return_value = [
        {"inid": "52", "value": "C08L 5/04"},
    ]
    cliente.get_listing_data.return_value = {
        "objects": [{"value": ["5ª Anuidade", "123", "", "", "R$ 100,00",
                               "01/01/2026", '<span>Averbada</span>']}],
    }

    chamadas = []
    monkeypatch.setattr(
        "inpi.coleta_plataforma_nova.registrar",
        lambda *a, **kw: chamadas.append((a, kw)) or True,
    )

    resumo = coletar_e_registrar(cliente, ["102022010731"], "clarke")

    assert resumo == {"registrados": 1, "sem_biblio": 0,
                      "ja_coletado_ou_invalido": 0, "erros": 0,
                      "nao_encontrados": []}
    (numero, campos, escritorio, fonte, coletado_em), kwargs = chamadas[0]
    assert numero == "102022010731"
    assert campos["cpc"] == "C08L 5/04"
    assert campos["anuidades"] == [
        {"numero": "5", "status": "Averbada", "gru": "123",
         "valor": "R$ 100,00", "data_pagamento": "01/01/2026"},
    ]
    assert campos["peticoes"] == []
    assert escritorio == "clarke"
    assert fonte == "Módulo de Serviços de Patentes INPI (headless)"


def test_coletar_e_registrar_conta_erro_sem_derrubar_o_lote(monkeypatch):
    cliente = MagicMock()
    cliente.get_bibliographic_data.side_effect = PlataformaNovaError("500")
    monkeypatch.setattr("inpi.coleta_plataforma_nova.registrar", lambda *a, **kw: True)

    resumo = coletar_e_registrar(cliente, ["102022010731", "102022010732"], "clarke")

    assert resumo == {"registrados": 0, "sem_biblio": 0,
                      "ja_coletado_ou_invalido": 0, "erros": 2,
                      "nao_encontrados": []}


def test_coletar_e_registrar_separa_nao_encontrado_de_erro_generico(monkeypatch):
    cliente = MagicMock()
    cliente.get_bibliographic_data.side_effect = [
        PlataformaNovaError('status 400: {"text":"Pedido de patente não encontrado"}'),
        PlataformaNovaError("status 500: erro interno"),
    ]
    monkeypatch.setattr("inpi.coleta_plataforma_nova.registrar", lambda *a, **kw: True)

    resumo = coletar_e_registrar(cliente, ["PI8502923", "102022010732"], "clarke")

    assert resumo["nao_encontrados"] == ["PI8502923"]
    assert resumo["erros"] == 1


def test_nao_encontrado_detecta_mesmo_com_acento_malcodificado():
    assert _nao_encontrado(PlataformaNovaError('"text":"Pedido de patente n�o encontrado"'))
    assert not _nao_encontrado(PlataformaNovaError("status 500: timeout"))


def test_coletar_e_registrar_sem_biblio_nao_chama_listing(monkeypatch):
    cliente = MagicMock()
    cliente.get_bibliographic_data.return_value = []
    monkeypatch.setattr("inpi.coleta_plataforma_nova.registrar", lambda *a, **kw: True)

    resumo = coletar_e_registrar(cliente, ["102022010731"], "clarke")

    assert resumo["sem_biblio"] == 1
    cliente.get_listing_data.assert_not_called()


def test_coletar_com_fallback_pepi_sem_residuo_nao_chama_pepi(monkeypatch):
    cliente = MagicMock()
    cliente.get_bibliographic_data.return_value = [{"inid": "52", "value": "C08L 5/04"}]
    cliente.get_listing_data.return_value = {"objects": []}
    monkeypatch.setattr("inpi.coleta_plataforma_nova.registrar", lambda *a, **kw: True)

    chamou_pepi = []
    import inpi.coleta_ficha_extras as cfe
    monkeypatch.setattr(cfe, "varrer_e_registrar_paralelo",
                        lambda *a, **kw: chamou_pepi.append((a, kw)) or {})

    resumo = coletar_com_fallback_pepi(cliente, ["102022010731"], "clarke")

    assert chamou_pepi == []
    assert resumo["fallback_pepi"] == {"registrados": 0, "nao_encontrado": 0,
                                       "ja_coletado_ou_invalido": 0}
    assert "nao_encontrados" not in resumo


def test_coletar_com_fallback_pepi_roteia_residuo_pro_pepi(monkeypatch):
    cliente = MagicMock()
    cliente.get_bibliographic_data.side_effect = PlataformaNovaError(
        '"text":"Pedido de patente não encontrado"')
    monkeypatch.setattr("inpi.coleta_plataforma_nova.registrar", lambda *a, **kw: True)

    chamadas_pepi = []
    import inpi.coleta_ficha_extras as cfe
    monkeypatch.setattr(
        cfe, "varrer_e_registrar_paralelo",
        lambda numeros, escritorio, **kw: chamadas_pepi.append((numeros, escritorio, kw))
        or {"registrados": 1, "nao_encontrado": 0, "ja_coletado_ou_invalido": 0},
    )

    resumo = coletar_com_fallback_pepi(cliente, ["PI8502923"], "clarke")

    assert chamadas_pepi[0][0] == ["PI8502923"]
    assert chamadas_pepi[0][1] == "clarke"
    assert resumo["fallback_pepi"] == {"registrados": 1, "nao_encontrado": 0,
                                       "ja_coletado_ou_invalido": 0}


def test_erro_de_rede_generico_conta_como_erro_nao_propaga(monkeypatch):
    cliente = MagicMock()
    cliente.get_bibliographic_data.side_effect = [
        httpx.ConnectError("conexao recusada"),  # P1: erro de rede cru
        [{"inid": "52", "value": "A61K"}],        # P2: sucesso
    ]
    cliente.get_listing_data.return_value = {"objects": []}

    monkeypatch.setattr(mod, "registrar", lambda *a, **k: True)

    resumo = mod.coletar_e_registrar(cliente, ["P1", "P2"], escritorio_canonico=None)

    assert resumo["erros"] == 1
    assert resumo["registrados"] == 1
    assert resumo["nao_encontrados"] == []


def test_coletar_e_registrar_com_paralelismo_processa_tudo_e_soma_certo(monkeypatch):
    """paralelismo>1 nao pode perder contagem nem duplicar -- soma dos
    contadores deve bater com o total de numeros_inpi, nao importa a ordem
    de conclusao das threads."""
    cliente = MagicMock()

    def _biblio(numero_inpi):
        if numero_inpi == "P_ERRO":
            raise PlataformaNovaError("status 500: erro interno")
        return [{"inid": "52", "value": "A61K"}]

    cliente.get_bibliographic_data.side_effect = _biblio
    cliente.get_listing_data.return_value = {"objects": []}
    monkeypatch.setattr(mod, "registrar", lambda *a, **k: True)

    numeros = [f"P{i}" for i in range(20)] + ["P_ERRO"]
    resumo = mod.coletar_e_registrar(cliente, numeros, escritorio_canonico=None,
                                     paralelismo=8)

    assert resumo["registrados"] == 20
    assert resumo["erros"] == 1
    assert resumo["sem_biblio"] == 0
