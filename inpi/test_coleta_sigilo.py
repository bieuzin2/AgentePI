"""Regressao: derivacao de termos de busca e gravacao curada de procurador-sigilo.

termos_busca exclui erro de digitacao (inutil como termo de busca) e inclui
agente da casa. registrar recusa numero_inpi que nao existe ou que ja tem
procurador oficial -- sem isso o CSV curado infla com linhas que o merge do
ingest (inpi/ingest.py::_mescla_procuradores_sigilo) ja ignoraria.
"""

from __future__ import annotations

import duckdb
import pytest

from inpi import coleta_sigilo as m


def test_termos_busca_exclui_erro_digitacao_inclui_agente_da_casa():
    termos = m.termos_busca("CLARKE MODET")
    assert "CLARKE MODET" in termos
    assert "ORLANDO DE SOUZA" in termos  # agente da casa
    assert "CLAKE MODET" not in termos  # erro de digitacao
    assert "CLARCKE MODET" not in termos  # erro de digitacao


def test_termos_busca_escritorio_sem_apelidos_devolve_so_o_canonico():
    assert m.termos_busca("ESCRITORIO INEXISTENTE XYZ") == ["ESCRITORIO INEXISTENTE XYZ"]


def test_formatar_numero_busca_formato_unificado():
    assert m._formatar_numero_busca("102026015044") == "BR 10 2026 015044"


def test_formatar_numero_busca_formato_antigo_devolve_none():
    assert m._formatar_numero_busca("PI0903314") is None


class _RespostaFalsa:
    def __init__(self, text):
        self.text = text


_HTML_BUSCA = """<a href='/pePI/servlet/PatenteServletController?Action=detail&CodPedido=999&SearchParameter=x'>x</a>"""

_HTML_FICHA = """
<td align="right"><font class="alerta">(74)</font>&nbsp;<font class="normal"> Nome do Procurador:</font></td>
<td align="left"><font class="normal">&nbsp;
CLARKE, MODET PROPRIEDADE INTELECTUAL LTDA.
</font></td>
"""


def test_procurador_na_ficha_extrai_do_html(monkeypatch):
    chamadas = []

    def _requisitar_falso(metodo, url, host, **kwargs):
        chamadas.append((metodo, url, kwargs))
        if metodo == "post":
            return _RespostaFalsa(_HTML_BUSCA)
        return _RespostaFalsa(_HTML_FICHA)

    monkeypatch.setattr(m, "requisitar", _requisitar_falso)

    assert m.procurador_na_ficha("102026015044") == "CLARKE, MODET PROPRIEDADE INTELECTUAL LTDA."


def test_varrer_e_registrar_paralelo_nao_corrompe_csv_sob_concorrencia(tmp_path, monkeypatch):
    """126 numeros, paralelismo 5, cada _Trabalhador falso devolve um
    procurador deterministico (metade Clarke, metade outro escritorio) --
    sem rede real. Garante que o lock em torno de registrar() produz o mesmo
    resultado que o caminho sequencial produziria: sem linha duplicada, sem
    corrupcao de CSV, contagem batendo com o numero de numeros processados."""
    numeros = [f"1020260{i:05d}" for i in range(126)]

    con_teste = duckdb.connect(":memory:")
    con_teste.execute("CREATE TABLE biblio (numero_inpi VARCHAR)")
    con_teste.executemany("INSERT INTO biblio VALUES (?)", [[n] for n in numeros])
    con_teste.execute("CREATE TABLE procuradores (numero_inpi VARCHAR)")
    monkeypatch.setattr(m, "con", lambda: con_teste)
    monkeypatch.setattr(m, "CSV_SIGILO", tmp_path / "procuradores-sigilo.csv")

    def _procurador_falso(self, numero_inpi):
        i = int(numero_inpi[-5:])
        return "CLARKE MODET" if i % 2 == 0 else "OUTRO ESCRITORIO LTDA"

    monkeypatch.setattr(m._Trabalhador, "sessao_anonima", lambda self: True)
    monkeypatch.setattr(m._Trabalhador, "procurador_na_ficha", _procurador_falso)

    resumo = m.varrer_e_registrar_paralelo(numeros, "CLARKE MODET", paralelismo=5)

    assert resumo["registrados"] == 63
    assert resumo["outro_escritorio"] == 63
    linhas = m._le_csv()
    assert len(linhas) == 63
    assert len({l["numero_inpi"] for l in linhas}) == 63  # sem duplicata


def test_procurador_na_ficha_url_de_detalhe_e_unica_por_pedido(monkeypatch):
    """Regressao: requisitar() cacheia GET pela URL crua, SEM olhar kwargs['params'].
    Passar CodPedido via params= fazia toda ficha colidir na mesma chave de cache
    e devolver sempre a PRIMEIRA ficha buscada no processo -- bug real, pegou
    102026015110 devolvendo o procurador de 102026015044. A URL da ficha
    precisa carregar o CodPedido nela mesma (nao em kwargs['params'])."""
    codpedidos_buscados = ["111", "222"]
    urls_de_detalhe = []

    def _requisitar_falso(metodo, url, host, **kwargs):
        if metodo == "post":
            cod = codpedidos_buscados.pop(0)
            return _RespostaFalsa(
                f"<a href='...?Action=detail&CodPedido={cod}&SearchParameter=x'>x</a>"
            )
        urls_de_detalhe.append(url)
        assert "params" not in kwargs, "CodPedido tem que ir na URL, nao em params="
        return _RespostaFalsa(_HTML_FICHA)

    monkeypatch.setattr(m, "requisitar", _requisitar_falso)

    m.procurador_na_ficha("102026015044")
    m.procurador_na_ficha("102026015110")

    assert "CodPedido=111" in urls_de_detalhe[0]
    assert "CodPedido=222" in urls_de_detalhe[1]
    assert urls_de_detalhe[0] != urls_de_detalhe[1]


@pytest.fixture
def _con_teste(monkeypatch):
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE biblio (numero_inpi VARCHAR)")
    con.execute("INSERT INTO biblio VALUES ('102020000001'), ('102020000002')")
    con.execute("CREATE TABLE procuradores (numero_inpi VARCHAR)")
    con.execute("INSERT INTO procuradores VALUES ('102020000002')")  # ja tem oficial
    monkeypatch.setattr(m, "con", lambda: con)
    return con


def test_registrar_grava_numero_valido_e_sem_procurador(tmp_path, monkeypatch, _con_teste):
    monkeypatch.setattr(m, "CSV_SIGILO", tmp_path / "procuradores-sigilo.csv")

    ok = m.registrar("102020000001", "CLARKE MODET", "CLARKE MODET", "pePI", "2026-08-11")

    assert ok is True
    linhas = m._le_csv()
    assert len(linhas) == 1
    assert linhas[0]["numero_inpi"] == "102020000001"


def test_registrar_recusa_numero_que_nao_existe(tmp_path, monkeypatch, _con_teste):
    monkeypatch.setattr(m, "CSV_SIGILO", tmp_path / "procuradores-sigilo.csv")

    ok = m.registrar("999999999999", "CLARKE MODET", "CLARKE MODET", "pePI", "2026-08-11")

    assert ok is False
    assert m._le_csv() == []


def test_registrar_recusa_numero_que_ja_tem_procurador_oficial(tmp_path, monkeypatch, _con_teste):
    monkeypatch.setattr(m, "CSV_SIGILO", tmp_path / "procuradores-sigilo.csv")

    ok = m.registrar("102020000002", "CLARKE MODET", "CLARKE MODET", "pePI", "2026-08-11")

    assert ok is False
    assert m._le_csv() == []


def test_registrar_recusa_duplicata_ja_coletada(tmp_path, monkeypatch, _con_teste):
    monkeypatch.setattr(m, "CSV_SIGILO", tmp_path / "procuradores-sigilo.csv")
    m.registrar("102020000001", "CLARKE MODET", "CLARKE MODET", "pePI", "2026-08-11")

    ok = m.registrar("102020000001", "CLARKE MODET", "CLARKE MODET", "pePI", "2026-08-11")

    assert ok is False
    assert len(m._le_csv()) == 1
