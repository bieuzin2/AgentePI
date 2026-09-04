"""Regressao: parser de CPC/Peticoes/Anuidades da ficha do pePI.

Fixtures HTML minimas espelham a estrutura real capturada ao vivo em
2026-08-11 (ver inpi/coleta_ficha_extras.py) -- nao a pagina inteira, so o
suficiente pra exercitar cada extrator isoladamente.
"""

from __future__ import annotations

import duckdb
from bs4 import BeautifulSoup

from inpi import coleta_ficha_extras as m

_HTML_CAMPO_CPC = """
<tr>
  <td align="right"><font class="alerta">(52)</font>&nbsp;<font class="normal">Classificacao CPC:</font></td>
  <td align="left"><font class="normal">&nbsp;
    <a href="javascript:void(0)" class="normal"> A01B 13/14 </a>
  </font></td>
</tr>
"""

_HTML_CAMPO_TEXTO_SIMPLES = """
<tr>
  <td align="right"><font class="alerta">(74)</font>&nbsp;<font class="normal">Nome do Procurador:</font></td>
  <td align="left"><font class="normal">&nbsp; CLARKE MODET </font></td>
</tr>
"""

_HTML_ANUIDADE = """
<table border="1"><tbody>
  <tr><td align="center"><table><tr><td><font class="normal">3<span> anuidade</span>:</font></td></tr></table></td></tr>
  <tr><td align="left"><font class="normal"><span>Status:</span>OK</font><br/>
    <font class="normal"><span>GRU:</span>0000920604801000<span>Valor: R$</span>195.00</font><br/>
    <font class="normal"><span>Data Pagamento:</span>25/08/2006</font>
  </td></tr>
</tbody></table>
"""

_HTML_ANUIDADE_SEM_LANCAMENTO = """
<table border="1"><tbody>
  <tr><td align="center"><table><tr><td><font class="normal">22<span> anuidade</span>:</font></td></tr></table></td></tr>
  <tr><td align="left"><font class="normal"><span>Status:</span>Nao contem lancamentos</font></td></tr>
</tbody></table>
"""

_HTML_PETICOES = """
<table>
  <thead><tr><td>Servico</td><td>Protocolo</td></tr></thead>
  <tbody>
    <tr class="normal">
      <td>212|Descricao do Servico|212|Expedicao de carta-patente|Informacoes do Banco:|033 - Banco X|Data: 13/10/2014|Valor: R$235.0</td>
      <td>800140239600</td>
      <td>13/10/2014</td>
    </tr>
  </tbody>
</table>
"""


def test_campo_por_codigo_extrai_link_com_tooltip():
    soup = BeautifulSoup(_HTML_CAMPO_CPC, "html.parser")
    assert m.campo_por_codigo(soup, "(52)") == "A01B 13/14"


def test_campo_por_codigo_extrai_texto_simples():
    soup = BeautifulSoup(_HTML_CAMPO_TEXTO_SIMPLES, "html.parser")
    assert m.campo_por_codigo(soup, "(74)") == "CLARKE MODET"


def test_campo_por_codigo_ausente_devolve_none():
    soup = BeautifulSoup(_HTML_CAMPO_CPC, "html.parser")
    assert m.campo_por_codigo(soup, "(999)") is None


def test_extrair_anuidades_pega_status_gru_valor_data():
    soup = BeautifulSoup(_HTML_ANUIDADE, "html.parser")
    anuidades = m._extrair_anuidades(soup)
    assert anuidades == [{
        "numero": "3", "status": "OK", "gru": "0000920604801000",
        "valor": "195.00", "data_pagamento": "25/08/2006",
    }]


def test_extrair_anuidades_sem_lancamento_nao_quebra():
    soup = BeautifulSoup(_HTML_ANUIDADE_SEM_LANCAMENTO, "html.parser")
    anuidades = m._extrair_anuidades(soup)
    assert anuidades == [{"numero": "22", "status": "Nao contem lancamentos"}]


def test_extrair_anuidades_dedup_por_numero():
    soup = BeautifulSoup(_HTML_ANUIDADE + _HTML_ANUIDADE, "html.parser")
    assert len(m._extrair_anuidades(soup)) == 1


def test_extrair_peticoes_le_linha_normal():
    soup = BeautifulSoup(_HTML_PETICOES, "html.parser")
    peticoes = m._extrair_peticoes(soup)
    assert len(peticoes) == 1
    assert peticoes[0]["codigo"] == "212"
    assert peticoes[0]["protocolo"] == "800140239600"
    assert peticoes[0]["data_protocolo"] == "13/10/2014"
    assert peticoes[0]["valor"] == "235.0"


def test_extrair_peticoes_sem_tabela_devolve_vazio():
    soup = BeautifulSoup("<html></html>", "html.parser")
    assert m._extrair_peticoes(soup) == []


def test_extrair_campos_combina_tudo():
    html = _HTML_CAMPO_CPC + _HTML_ANUIDADE + _HTML_PETICOES
    campos = m.extrair_campos(html)
    assert campos["cpc"] == "A01B 13/14"
    assert len(campos["anuidades"]) == 1
    assert len(campos["peticoes"]) == 1


def test_registrar_grava_numero_valido(tmp_path, monkeypatch):
    con_teste = duckdb.connect(":memory:")
    con_teste.execute("CREATE TABLE biblio (numero_inpi VARCHAR)")
    con_teste.execute("INSERT INTO biblio VALUES ('102020000001')")
    monkeypatch.setattr(m, "con", lambda: con_teste)
    monkeypatch.setattr(m, "CSV_FICHA_EXTRAS", tmp_path / "ficha-extras.csv")
    monkeypatch.setattr(m, "_cache_coletados", None)

    campos = {"cpc": "A01B 13/14", "peticoes": [{"codigo": "212"}], "anuidades": []}
    ok = m.registrar("102020000001", campos, "CLARKE MODET", "pePI", "2026-08-11")

    assert ok is True
    linhas = m._le_csv()
    assert len(linhas) == 1
    assert linhas[0]["cpc"] == "A01B 13/14"
    assert '"codigo": "212"' in linhas[0]["peticoes_json"]


def test_registrar_recusa_numero_que_nao_existe(tmp_path, monkeypatch):
    con_teste = duckdb.connect(":memory:")
    con_teste.execute("CREATE TABLE biblio (numero_inpi VARCHAR)")
    monkeypatch.setattr(m, "con", lambda: con_teste)
    monkeypatch.setattr(m, "CSV_FICHA_EXTRAS", tmp_path / "ficha-extras.csv")
    monkeypatch.setattr(m, "_cache_coletados", None)

    ok = m.registrar("999999999999", {}, "CLARKE MODET", "pePI", "2026-08-11")

    assert ok is False
    assert m._le_csv() == []


def test_registrar_recusa_duplicata_ja_coletada(tmp_path, monkeypatch):
    con_teste = duckdb.connect(":memory:")
    con_teste.execute("CREATE TABLE biblio (numero_inpi VARCHAR)")
    con_teste.execute("INSERT INTO biblio VALUES ('102020000001')")
    monkeypatch.setattr(m, "con", lambda: con_teste)
    monkeypatch.setattr(m, "CSV_FICHA_EXTRAS", tmp_path / "ficha-extras.csv")
    monkeypatch.setattr(m, "_cache_coletados", None)
    m.registrar("102020000001", {}, "CLARKE MODET", "pePI", "2026-08-11")

    ok = m.registrar("102020000001", {}, "CLARKE MODET", "pePI", "2026-08-11")

    assert ok is False
    assert len(m._le_csv()) == 1


def test_registrar_com_atualizar_apenda_recoleta_mais_nova(tmp_path, monkeypatch):
    """C1: sem isto o incremento faz a ida na rede e joga o resultado fora --
    coletado_em nunca avanca e o watermark nunca sai da lista de vencidos."""
    con_teste = duckdb.connect(":memory:")
    con_teste.execute("CREATE TABLE biblio (numero_inpi VARCHAR)")
    con_teste.execute("INSERT INTO biblio VALUES ('102020000001')")
    monkeypatch.setattr(m, "con", lambda: con_teste)
    monkeypatch.setattr(m, "CSV_FICHA_EXTRAS", tmp_path / "ficha-extras.csv")
    monkeypatch.setattr(m, "_cache_coletados", None)
    m.registrar("102020000001", {"cpc": "A01B"}, "CLARKE MODET", "pePI", "2026-08-11")

    ok = m.registrar("102020000001", {"cpc": "C07D"}, "CLARKE MODET", "pePI",
                     "2026-09-04", atualizar=True)

    assert ok is True
    linhas = m._le_csv()
    assert len(linhas) == 2
    assert linhas[-1]["coletado_em"] == "2026-09-04"
