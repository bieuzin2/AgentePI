"""Testes da auditoria de vigencia (EPO e banco mockados)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import inpi.vigencia as vg


ESTADOS = {
    "BR1": {"encerrado_em": None},
    "BR2": {"encerrado_em": None},
    "BR3": {"encerrado_em": "2020-01-01"},  # encerrado: fora da auditoria
}

FAMILIAS = {
    "BR1": {"membros": [
        {"pais": "EP", "referencia": "EP-1-B1"},
        {"pais": "US", "referencia": "US-1-B2"}]},
    "BR2": {"membros": [{"pais": "US", "referencia": "US-2-B2"}]},  # sem EP
}

STATUS = {"caducado_em": ["DE", "FR"], "taxa_nacional_paga_em": ["NL"],
          "paises_com_evento_nacional": ["DE", "FR", "NL"]}


def _con_mock(depositantes):
    con = MagicMock()
    con.execute.return_value.fetchall.return_value = [(d,) for d in depositantes]
    return con


def test_auditoria_alerta_caducidade_e_pula_sem_ep():
    biblio = {"documentos": [{"titulares": ["ACME CORP"]}]}
    with patch.object(vg, "_carregar_lote", return_value=(ESTADOS, 3)), \
         patch.object(vg, "familia", side_effect=lambda n: FAMILIAS[n]), \
         patch("epo.epo_mcp.epo_status_legal", return_value=STATUS), \
         patch("epo.epo_mcp.epo_biblio", return_value=biblio), \
         patch.object(vg, "chave_de", return_value="ACME"), \
         patch.object(vg, "resolver", return_value={"nivel": "curada", "chave": "ACME"}), \
         patch("inpi.db.con", return_value=_con_mock(["ACME CORP LTDA"])):
        r = vg.carteira_auditoria_vigencia("Cliente X")

    assert r["casos_ativos"] == 2
    assert r["casos_auditados"] == 1
    assert [a["pais"] for a in r["alertas_caducidade"]] == ["DE", "FR"]
    assert r["nao_auditados"][0]["numero_inpi"] == "BR2"
    assert r["nao_auditados"][0]["paises"] == ["US"]
    # 'ACME CORP LTDA' normaliza para 'ACME CORP' -> sem flag de qualidade
    assert r["qualidade_dados"] == []
    assert r["normalizacao"]["nivel"] == "curada"


def test_qualidade_dados_flag_quando_titular_diverge():
    biblio = {"documentos": [{"titulares": ["OUTRA EMPRESA GMBH"]}]}
    with patch.object(vg, "_carregar_lote",
                      return_value=({"BR1": {"encerrado_em": None}}, 1)), \
         patch.object(vg, "familia", side_effect=lambda n: FAMILIAS[n]), \
         patch("epo.epo_mcp.epo_status_legal", return_value=STATUS), \
         patch("epo.epo_mcp.epo_biblio", return_value=biblio), \
         patch.object(vg, "chave_de", return_value="X"), \
         patch.object(vg, "resolver", return_value={"nivel": "automatica", "chave": "X"}), \
         patch("inpi.db.con", return_value=_con_mock(["ACME CORP"])):
        r = vg.carteira_auditoria_vigencia("Cliente X")

    assert len(r["qualidade_dados"]) == 1
    q = r["qualidade_dados"][0]
    assert q["titular_inpi"] == ["ACME CORP"]
    assert q["titular_epo"] == ["OUTRA EMPRESA GMBH"]


def test_familia_com_erro_vira_sem_familia():
    with patch.object(vg, "_carregar_lote",
                      return_value=({"BR9": {"encerrado_em": None}}, 1)), \
         patch.object(vg, "familia", return_value={"erro": "404", "membros": []}), \
         patch.object(vg, "chave_de", return_value="X"), \
         patch.object(vg, "resolver", return_value={"nivel": "automatica", "chave": "X"}):
        r = vg.carteira_auditoria_vigencia("Cliente X")
    assert r["sem_familia_consultada"] == ["BR9"]
    assert r["casos_auditados"] == 0
