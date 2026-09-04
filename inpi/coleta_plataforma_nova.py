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


def _nao_encontrado(exc: PlataformaNovaError) -> bool:
    """Distingue 'processo nao existe na plataforma nova' (residuo esperado,
    ~21% do formato legado, ver docs/pesquisa/inpi_plataforma_nova.md secao
    5b) de erro de rede/servidor genuino -- so o primeiro caso deve cair pro
    fallback do pePI. 'ncontrado' (sem o 'e' inicial) casa com a mensagem
    mesmo quando o 'a' acentuado vem mal-decodificado pelo servidor."""
    return "ncontrado" in str(exc)


def coletar_e_registrar(
    cliente: ClientePlataformaNova, numeros_inpi: list[str],
    escritorio_canonico: str, fonte: str = FONTE_PADRAO,
    atualizar: bool = False,
) -> dict[str, Any]:
    """Para cada numero_inpi: busca biblio (pra CPC) + anuidades, mapeia pro
    shape do registrar() existente, grava. Erro de rede/API num processo NAO
    derruba o lote inteiro -- so conta e segue pro proximo. 'nao_encontrados'
    (lista, nao so contagem) e o residuo que coletar_com_fallback_pepi()
    reprocessa via pePI; 'erros' e falha genuina (rede/servidor), nao
    reprocessada automaticamente."""
    resumo: dict[str, Any] = {"registrados": 0, "sem_biblio": 0,
                              "ja_coletado_ou_invalido": 0, "erros": 0,
                              "nao_encontrados": []}
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
                           date.today().isoformat(), atualizar=atualizar)
            resumo["registrados" if ok else "ja_coletado_ou_invalido"] += 1
        except PlataformaNovaError as exc:
            if _nao_encontrado(exc):
                resumo["nao_encontrados"].append(numero_inpi)
            else:
                resumo["erros"] += 1
    return resumo


def coletar_com_fallback_pepi(
    cliente: ClientePlataformaNova, numeros_inpi: list[str],
    escritorio_canonico: str, fonte: str = FONTE_PADRAO, paralelismo: int = 4,
    atualizar: bool = False,
) -> dict[str, Any]:
    """Plataforma nova como fonte PRIMARIA pros tres recortes (moderno,
    sigilo, legado -- todos validados, ver docs/pesquisa/inpi_plataforma_nova.md);
    o residuo que ela devolver 'nao encontrado' (na pratica quase so formato
    legado, ~21% dele) cai automaticamente pro pePI (inpi.coleta_ficha_extras,
    mesmo paralelismo/circuit-breaker de sempre). Import local de
    coleta_ficha_extras.varrer_e_registrar_paralelo pra nao forcar abertura
    de sessao Tor/pePI em quem so usa coletar_e_registrar (o caso comum,
    moderno/sigilo, nunca precisa do pePI)."""
    resumo = coletar_e_registrar(cliente, numeros_inpi, escritorio_canonico, fonte,
                                 atualizar=atualizar)
    residuo = resumo.pop("nao_encontrados")
    if not residuo:
        resumo["fallback_pepi"] = {"registrados": 0, "nao_encontrado": 0,
                                   "ja_coletado_ou_invalido": 0}
        return resumo

    from inpi.coleta_ficha_extras import varrer_e_registrar_paralelo

    resumo["fallback_pepi"] = varrer_e_registrar_paralelo(
        residuo, escritorio_canonico, paralelismo=paralelismo,
        fonte="pePI busca.inpi.gov.br (fallback da plataforma nova)",
        atualizar=atualizar,
    )
    return resumo
