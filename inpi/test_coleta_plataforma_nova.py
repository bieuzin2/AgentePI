from __future__ import annotations

from unittest.mock import MagicMock

from inpi.coleta_plataforma_nova import (
    _extrair_cpc,
    _mapear_anuidade,
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
                      "ja_coletado_ou_invalido": 0, "erros": 0}
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
                      "ja_coletado_ou_invalido": 0, "erros": 2}


def test_coletar_e_registrar_sem_biblio_nao_chama_listing(monkeypatch):
    cliente = MagicMock()
    cliente.get_bibliographic_data.return_value = []
    monkeypatch.setattr("inpi.coleta_plataforma_nova.registrar", lambda *a, **kw: True)

    resumo = coletar_e_registrar(cliente, ["102022010731"], "clarke")

    assert resumo["sem_biblio"] == 1
    cliente.get_listing_data.assert_not_called()
