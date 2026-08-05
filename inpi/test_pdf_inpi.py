"""Testes do parser de secoes e quadro reivindicatorio. Sem rede, sem PDF real
disponivel neste ambiente (portal do INPI sem endpoint estavel -- ver
docs/aceite/F4-pdf-claimchart.md) -- fixture de texto sintetico simula a estrutura
oficial de um pedido BR publicado.
"""

from inpi import pdf_inpi as pi

TEXTO_SINTETICO = """
RELATORIO DESCRITIVO

A presente invencao refere-se a um dispositivo de fixacao mecanica.

RESUMO

Dispositivo de fixacao compreendendo uma haste e um encaixe.

REIVINDICACOES

1. Dispositivo de fixacao caracterizado por compreender uma haste (1) e um
encaixe (2).

2. Dispositivo de acordo com a reivindicacao 1, caracterizado pelo fato de a
haste (1) ser rosqueada.

3. Dispositivo de acordo com qualquer uma das reivindicacoes anteriores,
caracterizado por ainda compreender uma trava (3).
"""


def test_parse_secoes_acha_os_tres_marcadores():
    r = pi.parse_secoes(TEXTO_SINTETICO)
    assert set(r["secoes_encontradas"]) == {"resumo", "descritivo", "reivindicacoes"}
    assert "desenhos" in r["secoes_ausentes"]
    assert "haste (1)" in r["reivindicacoes"]
    assert "dispositivo de fixacao" in r["descritivo"].lower()


def test_parse_secoes_texto_sem_marcador_nao_inventa_secao():
    r = pi.parse_secoes("texto qualquer sem estrutura oficial")
    assert r["secoes_encontradas"] == []
    assert set(r["secoes_ausentes"]) == set(pi.MARCADORES_SECAO)


def test_quadro_reivindicatorio_separa_por_numero():
    r = pi.parse_secoes(TEXTO_SINTETICO)
    itens = pi.quadro_reivindicatorio(r["reivindicacoes"])
    assert [i["numero"] for i in itens] == [1, 2, 3]
    assert "haste (1)" in itens[0]["texto"]
    assert "rosqueada" in itens[1]["texto"]


def test_quadro_reivindicatorio_vazio_sem_secao():
    assert pi.quadro_reivindicatorio("") == []


def test_quadro_reivindicatorio_sem_numeracao_devolve_bloco_unico():
    itens = pi.quadro_reivindicatorio("texto corrido sem numeros")
    assert len(itens) == 1
    assert itens[0]["numero"] is None


def test_baixar_pdf_sem_arquivo_local_devolve_fallback_manual(tmp_path, monkeypatch):
    monkeypatch.setattr(pi, "PASTA_PDFS", tmp_path)
    r = pi.baixar_pdf("BR 10 2022 010731 2")
    assert r["ok"] is False
    assert "manualmente" in r["mensagem"]
    assert r["caminho_esperado"].endswith("102022010731.pdf")


def test_baixar_pdf_acha_arquivo_salvo_manualmente(tmp_path, monkeypatch):
    monkeypatch.setattr(pi, "PASTA_PDFS", tmp_path)
    destino = tmp_path / "102022010731.pdf"
    destino.write_bytes(b"%PDF-1.4 fake")
    r = pi.baixar_pdf("102022010731")
    assert r["ok"] is True
    assert r["origem"] == "arquivo_local"


def test_carregar_sem_pdf_devolve_erro_com_caminho_esperado(tmp_path, monkeypatch):
    monkeypatch.setattr(pi, "PASTA_PDFS", tmp_path)
    r = pi.carregar("102022010731")
    assert r["erro"] is True
    assert "caminho_esperado" in r
