"""Testes de inpi/mercado_fila.py contra um arquivo DuckDB proprio em
tmp_path -- sem rede, sem tocar inpi.duckdb nem fila_mercado.duckdb real."""

from __future__ import annotations

from unittest.mock import patch

import duckdb

import inpi.mercado_fila as fila


def test_proximo_lote_prioriza_concorrente_antes_de_nacional(monkeypatch, tmp_path):
    banco = tmp_path / "fila_mercado.duckdb"
    monkeypatch.setattr(fila, "BANCO_FILA", banco)

    con = fila._con()
    con.execute(
        "INSERT INTO fila_mercado VALUES "
        "('N1', 'nacional', 'pendente', 0, '2026-09-01'), "
        "('C1', 'concorrente', 'pendente', 0, '2026-09-01'), "
        "('C2', 'concorrente', 'pendente', 0, '2026-09-01')"
    )
    con.close()

    lote = fila.proximo_lote(2)

    assert lote == ["C1", "C2"]


def test_marcar_atualiza_status(monkeypatch, tmp_path):
    banco = tmp_path / "fila_mercado.duckdb"
    monkeypatch.setattr(fila, "BANCO_FILA", banco)

    con = fila._con()
    con.execute(
        "INSERT INTO fila_mercado VALUES "
        "('N1', 'nacional', 'pendente', 0, '2026-09-01')"
    )
    con.close()

    fila.marcar(["N1"], "coletado")

    con = fila._con()
    status = con.execute(
        "SELECT status FROM fila_mercado WHERE numero_inpi = 'N1'"
    ).fetchone()[0]
    con.close()
    assert status == "coletado"


def test_proximo_lote_ignora_ja_coletados(monkeypatch, tmp_path):
    banco = tmp_path / "fila_mercado.duckdb"
    monkeypatch.setattr(fila, "BANCO_FILA", banco)

    con = fila._con()
    con.execute(
        "INSERT INTO fila_mercado VALUES "
        "('N1', 'nacional', 'coletado', 1, '2026-09-01'), "
        "('N2', 'nacional', 'pendente', 0, '2026-09-01')"
    )
    con.close()

    assert fila.proximo_lote(10) == ["N2"]


def test_popular_nacional_insere_apenas_depositos_recentes_e_novos(monkeypatch, tmp_path):
    banco_fila = tmp_path / "fila_mercado.duckdb"
    monkeypatch.setattr(fila, "BANCO_FILA", banco_fila)

    banco_inpi = tmp_path / "inpi.duckdb"
    con_inpi = duckdb.connect(str(banco_inpi))
    con_inpi.execute("CREATE TABLE biblio (numero_inpi VARCHAR, data_deposito DATE)")
    con_inpi.execute(
        "INSERT INTO biblio VALUES "
        "('P1', DATE '2021-01-01'), "  # recente, mas ja esta na fila
        "('P2', DATE '2015-01-01'), "  # antigo, nao deve entrar
        "('P3', DATE '2022-01-01')"    # recente e novo, deve entrar
    )
    con_inpi.close()
    monkeypatch.setattr(fila, "_con_inpi",
                        lambda: duckdb.connect(str(banco_inpi), read_only=True))

    # P1 ja esta na fila (de popular_concorrentes, por ex.) -- nao duplica.
    con = fila._con()
    con.execute(
        "INSERT INTO fila_mercado VALUES "
        "('P1', 'concorrente', 'pendente', 0, '2026-09-01')"
    )
    con.close()

    resultado = fila.popular_nacional(desde="2020-01-01")

    con = fila._con()
    linhas = con.execute(
        "SELECT numero_inpi, origem FROM fila_mercado ORDER BY numero_inpi"
    ).fetchall()
    con.close()

    assert resultado == {"inseridos": 1}
    assert linhas == [("P1", "concorrente"), ("P3", "nacional")]  # P1 nao duplicou, P2 ficou de fora


def test_popular_concorrentes_resolve_titulares_e_insere_numeros(monkeypatch, tmp_path):
    banco_fila = tmp_path / "fila_mercado.duckdb"
    monkeypatch.setattr(fila, "BANCO_FILA", banco_fila)

    clientes_csv = tmp_path / "clientes-clarke.csv"
    clientes_csv.write_text(
        "chave_canonica,nome_exibicao,processos,grafias\n"
        "HUAWEI TECHNOLOGIES,\"HUAWEI TECHNOLOGIES CO., LTD.\",2157,16\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(fila, "CLIENTES_CURADOS", clientes_csv)

    landscape_resultado = {
        "por_cpc": {
            "H01L": {
                "top_titulares_mundiais": [
                    {"titular": "SAMSUNG ELECTRONICS", "depositos": 500},
                ],
            },
        },
    }

    def _fake_chaves_de(nome):
        assert nome == "SAMSUNG ELECTRONICS"
        return [{"chave": "SAMSUNG ELECTRONICS CO LTD", "processos": 10,
                 "exemplo": "Samsung Electronics Co., Ltd."}]

    def _fake_numeros_do_titular(con, chave):
        assert chave == "SAMSUNG ELECTRONICS CO LTD"
        return ["S1", "S2"]

    with patch("inpi.mercado_fila.landscape_carteira",
               return_value=landscape_resultado) as mock_landscape, \
         patch("inpi.mercado_fila.chaves_de", side_effect=_fake_chaves_de), \
         patch("inpi.mercado_fila._numeros_do_titular",
               side_effect=_fake_numeros_do_titular), \
         patch("inpi.mercado_fila._con_inpi"):
        resultado = fila.popular_concorrentes(top_cpc=3, limite_titulares_por_cpc=10)

    mock_landscape.assert_called_once_with(
        cliente="HUAWEI TECHNOLOGIES CO., LTD.", top_cpc=3,
        confirmar_acima_10gb=False)

    con = fila._con()
    linhas = sorted(r[0] for r in con.execute(
        "SELECT numero_inpi FROM fila_mercado"
    ).fetchall())
    con.close()

    assert linhas == ["S1", "S2"]
    assert resultado == {"inseridos": 2, "titulares_resolvidos": 1,
                         "titulares_nao_resolvidos": []}


def test_popular_concorrentes_sem_csv_de_clientes_nao_faz_nada(monkeypatch, tmp_path):
    monkeypatch.setattr(fila, "BANCO_FILA", tmp_path / "fila_mercado.duckdb")
    monkeypatch.setattr(fila, "CLIENTES_CURADOS", tmp_path / "nao-existe.csv")

    resultado = fila.popular_concorrentes()

    assert resultado == {"inseridos": 0, "titulares_resolvidos": 0,
                         "titulares_nao_resolvidos": []}
