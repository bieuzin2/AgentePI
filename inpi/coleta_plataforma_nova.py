"""Coleta via o Modulo de Servicos de Patentes (plataforma nova, headless,
ver inpi/plataforma_nova.py) e grava no MESMO ficha-extras.csv que
inpi/coleta_ficha_extras.py usa -- reusa registrar() sem tocar no schema
(ficha_extras/ficha_peticoes/ficha_anuidades continuam vindo do mesmo CSV
via inpi/ingest.py).

'peticoes' sai sempre vazio aqui: 'Eventos de Pedido' (a outra aba da
plataforma nova) NAO foi confirmado como equivalente a 'Peticoes/Servicos'
do pePI (podem ser conceitos diferentes -- despacho processual vs peticao
protocolada com GRU). Ate confirmar isso na validacao de volume (ver
inpi/validar_plataforma_nova.py), so anuidades e coletado daqui; peticoes
continua vindo so do pePI.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from inpi.coleta_ficha_extras import registrar
from inpi.plataforma_nova import ClientePlataformaNova, PlataformaNovaError

FONTE_PADRAO = "Módulo de Serviços de Patentes INPI (headless)"


def _mapear_anuidade(value: list) -> dict[str, Any]:
    """Traduz uma linha de getListingData(tipo='anuidades') (array posicional
    'value', ordem confirmada ao vivo: Anuidade, GRU, prazo ordinario, prazo
    extraordinario, valor pago, data de pagamento, situacao da averbacao em
    HTML) pro mesmo shape que o parser do pePI ja produz (numero/status/gru/
    valor/data_pagamento) -- so assim ficha_anuidades continua com um schema
    so, nao importa a fonte."""
    campos = list(value) + [None] * (7 - len(value))
    rotulo, gru, _prazo_ord, _prazo_extra, valor, data_pagamento, situacao_html = campos[:7]
    m = re.search(r"\d+", rotulo or "")
    situacao = BeautifulSoup(situacao_html or "", "html.parser").get_text(strip=True)
    return {
        "numero": m.group(0) if m else None,
        "status": situacao or None,
        "gru": gru or None,
        "valor": valor or None,
        "data_pagamento": data_pagamento or None,
    }


def _extrair_cpc(biblio: list[dict[str, Any]]) -> str | None:
    """Campo INID 52 ('Classificacao Nacional') -- mesmo campo que o parser
    do pePI le como CPC (ver campo_por_codigo(soup, '(52)') em
    coleta_ficha_extras.py)."""
    for campo in biblio:
        if campo.get("inid") == "52":
            return campo.get("value") or None
    return None


def coletar_e_registrar(
    cliente: ClientePlataformaNova, numeros_inpi: list[str],
    escritorio_canonico: str, fonte: str = FONTE_PADRAO,
) -> dict[str, int]:
    """Para cada numero_inpi: busca biblio (pra CPC) + anuidades, mapeia pro
    shape do registrar() existente, grava. Erro de rede/API num processo NAO
    derruba o lote inteiro -- so conta em 'erros' e segue pro proximo."""
    resumo = {"registrados": 0, "sem_biblio": 0, "ja_coletado_ou_invalido": 0, "erros": 0}
    for numero_inpi in numeros_inpi:
        try:
            biblio = cliente.get_bibliographic_data(numero_inpi)
            if not biblio:
                resumo["sem_biblio"] += 1
                continue
            listagem = cliente.get_listing_data(numero_inpi, "anuidades")
            anuidades = [_mapear_anuidade(obj["value"])
                        for obj in listagem.get("objects", [])]
            campos = {"cpc": _extrair_cpc(biblio), "peticoes": [], "anuidades": anuidades}
            ok = registrar(numero_inpi, campos, escritorio_canonico, fonte,
                           date.today().isoformat())
            resumo["registrados" if ok else "ja_coletado_ou_invalido"] += 1
        except PlataformaNovaError:
            resumo["erros"] += 1
    return resumo
