"""Testes do inpi_mcp.

Os de normalizacao e de prazo rodam sem banco. Os de consulta so rodam se o
DuckDB local existir (pulam sozinhos em maquina que ainda nao ingeriu).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import inpi_mcp as m

precisa_banco = pytest.mark.skipif(
    not m.BANCO.exists(), reason="banco ausente; rode python inpi/ingest.py"
)


# --- normalizacao de numero -------------------------------------------------

@pytest.mark.parametrize(
    "entrada",
    [
        "102022010731",            # como o INPI guarda
        "BR102022010731",          # com prefixo de pais
        "BR-102022010731-A2",      # como o EPO devolve
        "BR 10 2022 010731 2",     # forma impressa, com digito verificador
        "br 10 2022 010731 2",
        "BR.102022010731.A2",
    ],
)
def test_normaliza_todas_as_formas_do_mesmo_processo(entrada):
    """Regressao: as tres fontes escrevem o mesmo processo de formas diferentes.
    Se a normalizacao falhar, o agente conclui 'processo nao encontrado' sobre um
    pedido que existe -- e isso vira 'sem anterioridade' no parecer."""
    assert m.normaliza_numero(entrada) == "102022010731"


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("PI1107322", "PI1107322"),      # legado nao perde o prefixo
        ("MU8600325", "MU8600325"),
        ("pi 1107322", "PI1107322"),
        ("112025001485", "112025001485"),
    ],
)
def test_normaliza_preserva_formato_legado(entrada, esperado):
    assert m.normaliza_numero(entrada) == esperado


# --- prazo declarado --------------------------------------------------------

def test_prazo_so_e_lido_quando_o_inpi_escreveu():
    """Medimos que apenas 1% dos despachos declaram 'N dias'. O tool NAO calcula
    prazo por analogia -- ausencia tem que devolver None, nunca um chute."""
    texto = ("Teor da exigência disponível no parecer (pdf). Prazo para cumprimento "
             "- 30 (Trinta) dias corridos contados do 1º dia útil após essa publicação")
    assert m._prazo_declarado(texto) == 30
    assert m._prazo_declarado("Reconhecida a justa causa, CONCEDIDO o prazo de 46 "
                              "(quarenta e seis) dias, contados da publicação no RPI") == 46
    assert m._prazo_declarado("") is None
    assert m._prazo_declarado(None) is None
    # 'prazo' sem numero de dias nao vira prazo
    assert m._prazo_declarado("Arquivamento da petição de prazo nº01670004313") is None


def test_prazo_ja_perdido_nao_vira_prazo_ativo():
    """Regressao do pior falso positivo possivel. Texto real do despacho 11.2:
    o '90 dias' citado e o prazo que JA FOI PERDIDO e que causou o arquivamento.
    Le-lo como prazo a correr diria que ha tres meses para agir sobre um pedido morto."""
    texto_11_2 = (
        "Arquivo o pedido de patente de invenção, conforme o disposto no art. 36 § 1° "
        "da LPI (Lei 9279 / 96) de 14/05/1996, em face da não apresentação de "
        "cumprimento da exigência notificada na RPI n° 2596 de 06/10/2020 em até "
        "90 (noventa) dias."
    )
    assert m._prazo_declarado(texto_11_2) is None


def test_dois_prazos_no_mesmo_texto_e_ambiguo():
    """Texto real do 11.6.1: cita o prazo perdido E o prazo de recurso. Escolher
    um dos dois seria chute; devolver None manda ler o texto literal."""
    texto_11_6_1 = (
        "Arquivada a petição, uma vez que não foi apresentada a procuração devida no "
        "prazo de 60 ( sessenta) dias contados da prática do ato. Desta data corre o "
        "prazo de 60 ( sessenta ) dias para eventual recurso do interessado"
    )
    assert m._prazo_declarado(texto_11_6_1) is None


# --- consultas (exigem banco) -----------------------------------------------

@precisa_banco
def test_processo_real_traz_ficha_completa():
    d = m.inpi_processo("BR-102022010731-A2")
    assert not d.get("erro")
    assert d["numero_inpi"] == "102022010731"
    assert "ALGINATO" in (d["titulo"] or "").upper()
    # dedup na ingestao: os CSVs do INPI repetem a mesma linha varias vezes
    assert d["depositantes"] == sorted(d["depositantes"], key=lambda x: x["ordem"])
    assert len(d["depositantes"]) == 1, "titular duplicado -> dedup da ingestao quebrou"
    assert len(d["inventores"]) == 4
    assert len(set(d["ipc"])) == len(d["ipc"]), "IPC duplicado"
    assert len(d["despachos"]) >= 8
    # o despacho 2.5 declara 30 dias no proprio texto
    assert any(x["dias_citados_no_texto"] == 30 for x in d["despachos"])


@precisa_banco
def test_processo_inexistente_falha_alto():
    d = m.inpi_processo("999999999999")
    assert d["erro"] is True and "nao encontrado" in d["mensagem"].lower()


@precisa_banco
def test_busca_texto_exige_todos_os_termos():
    d = m.inpi_busca_texto("biodegrad embalag", campo="ambos", limite=5)
    assert d["retornados"] > 0
    assert all(t in d["termos"] for t in ("biodegrad", "embalag"))


@precisa_banco
def test_busca_texto_recusa_campo_invalido():
    assert m.inpi_busca_texto("teste", campo="reivindicacoes").get("erro") is True


@precisa_banco
def test_busca_ipc_por_prefixo():
    d = m.inpi_busca_ipc("B65D 65/46", limite=5)
    assert d["retornados"] > 0
    assert all(r["simbolo"].startswith("B65D 65/46") for r in d["resultados"])


@precisa_banco
def test_despachos_exige_algum_filtro():
    assert m.inpi_despachos_por_rpi().get("erro") is True


@precisa_banco
def test_cobertura_declara_a_data_de_corte():
    """Sem data de corte declarada, um resultado vazio nao prova ausencia de nada."""
    c = m.inpi_cobertura()
    assert c["ultimo_numero_rpi"] > 2800
    assert c["despachos"] > 5_000_000
