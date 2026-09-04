from __future__ import annotations

import csv

from inpi.estatistica_publica import _CAMPOS, _linha_csv, gravar_csv


def test_linha_csv_traduz_camelcase_pra_snake_case():
    linha_js = {
        "ano": 2000, "tipoAtivo": "Patentes", "subTipo": "Patente de Invenção",
        "tipoPatente": "Patente de Invenção", "viaEntrada": "PCT",
        "origem": "Residente", "pais": "Brasil", "uf": "Diversas UF",
        "regiao": "Brasil", "campoTecnologico": "Química", "decisao": "Concessão",
        "anoDecisao": 2000, "depositos": 283, "concessoes": 91,
        "nDecisoes": 91, "nVigentes": 0,
    }
    linha = _linha_csv(linha_js, coletado_em="2026-09-04")

    assert linha["ano"] == 2000
    assert linha["tipo_ativo"] == "Patentes"
    assert linha["campo_tecnologico"] == "Química"
    assert linha["n_vigentes"] == 0
    assert linha["coletado_em"] == "2026-09-04"


def test_linha_csv_com_campo_ausente_usa_string_vazia():
    linha = _linha_csv({"ano": 2000, "tipoAtivo": "Marcas"}, coletado_em="2026-09-04")
    assert linha["origem"] == ""
    assert linha["campo_tecnologico"] == ""


def test_gravar_csv_escreve_cabecalho_e_linhas(tmp_path):
    destino = tmp_path / "saida.csv"
    linhas_js = [
        {"ano": 2000, "tipoAtivo": "Patentes", "depositos": 283, "concessoes": 91,
         "nDecisoes": 91, "nVigentes": 0},
        {"ano": 2001, "tipoAtivo": "Patentes", "depositos": 300, "concessoes": 95,
         "nDecisoes": 95, "nVigentes": 5},
    ]

    n = gravar_csv(linhas_js, destino=destino, coletado_em="2026-09-04")

    assert n == 2
    with destino.open(encoding="utf-8") as fh:
        linhas = list(csv.DictReader(fh))
    assert [c for c in linhas[0]] == _CAMPOS
    assert linhas[0]["ano"] == "2000"
    assert linhas[1]["depositos"] == "300"
