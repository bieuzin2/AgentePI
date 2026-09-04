"""Testes do modulo de priorizacao da coleta incremental (sem rede)."""

from __future__ import annotations

from datetime import date, timedelta

import duckdb

import vigilancia.incremento_plataforma_nova as inc

CHAVE = "CLARKE MODET"


def _cria_carteira(con, numeros=("P1", "P2", "P3")):
    """procuradores/escritorios minimos: so `numeros` sao da carteira Clarke;
    o resto da base (P9, outras bancas) tem de ficar de fora do incremento."""
    con.execute("CREATE TABLE procuradores (numero_inpi VARCHAR, procurador VARCHAR)")
    con.execute("CREATE TABLE escritorios (original VARCHAR, chave VARCHAR)")
    con.executemany("INSERT INTO procuradores VALUES (?, 'CLARKE MODET SA')",
                    [(n,) for n in numeros])
    con.execute("INSERT INTO procuradores VALUES ('P9', 'OUTRA BANCA')")
    con.execute("INSERT INTO escritorios VALUES ('CLARKE MODET SA', ?), ('OUTRA BANCA', 'OUTRA BANCA')",
                [CHAVE])


def test_numeros_despacho_novo_sem_banco_anterior_devolve_vazio(monkeypatch, tmp_path):
    monkeypatch.setattr(inc, "BANCO_ANTERIOR", tmp_path / "nao-existe.duckdb")
    monkeypatch.setattr(inc, "BANCO_INPI", tmp_path / "inpi.duckdb")
    assert inc.numeros_despacho_novo() == []


def test_numeros_despacho_novo_identifica_processo_com_despacho_novo(monkeypatch, tmp_path):
    antigo_path = tmp_path / "inpi_anterior.duckdb"
    novo_path = tmp_path / "inpi.duckdb"

    con_a = duckdb.connect(str(antigo_path))
    con_a.execute("CREATE TABLE despachos (numero_inpi VARCHAR, codigo_despacho VARCHAR, data_rpi VARCHAR)")
    con_a.execute("INSERT INTO despachos VALUES ('P1', '1.1', '2026-08-01')")
    con_a.close()

    con_n = duckdb.connect(str(novo_path))
    con_n.execute("CREATE TABLE despachos (numero_inpi VARCHAR, codigo_despacho VARCHAR, data_rpi VARCHAR)")
    # P1: mesmo despacho de antes (sem mudanca) + despacho novo -> conta como mudou.
    # P2: so existia antes, sumiu (nao deve aparecer -- so novidade importa aqui).
    # P3: despacho totalmente novo.
    # P9: despacho novo de OUTRA banca -- nao pode aparecer (I3).
    con_n.execute("""
        INSERT INTO despachos VALUES
            ('P1', '1.1', '2026-08-01'),
            ('P1', '2.1', '2026-08-29'),
            ('P3', '1.1', '2026-08-29'),
            ('P9', '1.1', '2026-08-29')
    """)
    _cria_carteira(con_n)
    con_n.close()

    monkeypatch.setattr(inc, "BANCO_ANTERIOR", antigo_path)
    monkeypatch.setattr(inc, "BANCO_INPI", novo_path)

    resultado = inc.numeros_despacho_novo()

    assert sorted(resultado) == ["P1", "P3"]


def test_numeros_watermark_vencido_sem_banco_devolve_vazio(monkeypatch, tmp_path):
    monkeypatch.setattr(inc, "BANCO_INPI", tmp_path / "nao-existe.duckdb")
    assert inc.numeros_watermark_vencido() == []


def test_numeros_watermark_vencido_pega_nunca_coletado_e_antigo(monkeypatch, tmp_path):
    banco = tmp_path / "inpi.duckdb"
    con = duckdb.connect(str(banco))
    con.execute("CREATE TABLE biblio (numero_inpi VARCHAR)")
    con.execute("INSERT INTO biblio VALUES ('P1'), ('P2'), ('P3'), ('P9')")
    con.execute("CREATE TABLE ficha_extras (numero_inpi VARCHAR, coletado_em VARCHAR)")
    recente = date.today().isoformat()
    antigo = (date.today() - timedelta(days=90)).isoformat()
    con.execute(
        "INSERT INTO ficha_extras VALUES (?, ?), (?, ?)",
        ["P1", recente, "P2", antigo],
    )
    # P3: nunca coletado (sem linha em ficha_extras) -- tambem deve entrar.
    # P9: vencido, mas de outra banca -- fora do escopo da carteira (C3).
    _cria_carteira(con)
    con.close()

    monkeypatch.setattr(inc, "BANCO_INPI", banco)

    resultado = inc.numeros_watermark_vencido(dias=60)

    assert sorted(resultado) == ["P2", "P3"]


def test_numeros_watermark_vencido_respeita_limite(monkeypatch, tmp_path):
    """C3: carteira recem-onboardada (tudo nunca coletado) nao pode inundar
    uma rodada -- o teto corta e o resto entra nas semanas seguintes."""
    banco = tmp_path / "inpi.duckdb"
    numeros = [f"Q{i}" for i in range(20)]
    con = duckdb.connect(str(banco))
    con.execute("CREATE TABLE biblio (numero_inpi VARCHAR)")
    con.executemany("INSERT INTO biblio VALUES (?)", [(n,) for n in numeros])
    con.execute("CREATE TABLE ficha_extras (numero_inpi VARCHAR, coletado_em VARCHAR)")
    _cria_carteira(con, numeros)
    con.close()

    monkeypatch.setattr(inc, "BANCO_INPI", banco)

    assert len(inc.numeros_watermark_vencido(dias=60, limite=5)) == 5


def test_rodar_incremento_sem_numeros_pula(monkeypatch):
    assert inc.rodar_incremento([]) == {
        "pulado": True, "mensagem": "nenhum numero_inpi na lista de prioridade."
    }


def test_rodar_incremento_sem_credencial_pula(monkeypatch):
    monkeypatch.delenv("INPI_PAG_LOGIN", raising=False)
    monkeypatch.delenv("INPI_PAG_PASSWORD", raising=False)
    r = inc.rodar_incremento(["P1"])
    assert r == {"pulado": True, "mensagem": "INPI_PAG_LOGIN/INPI_PAG_PASSWORD ausentes."}


def test_rodar_incremento_chama_coletar_com_fallback_pepi(monkeypatch):
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("INPI_PAG_LOGIN", "user")
    monkeypatch.setenv("INPI_PAG_PASSWORD", "pass")
    cliente_mock = MagicMock()
    with patch("inpi.plataforma_nova.ClientePlataformaNova", return_value=cliente_mock) as Cliente, \
         patch("inpi.coleta_plataforma_nova.coletar_com_fallback_pepi",
               return_value={"registrados": 1}) as coletar:
        r = inc.rodar_incremento(["P1", "P2"], escritorio_canonico="CLARKE MODET")

    Cliente.assert_called_once_with("user", "pass")
    # atualizar=True: sem isso registrar() descarta quem ja esta no CSV (C1).
    coletar.assert_called_once_with(cliente_mock, ["P1", "P2"], "CLARKE MODET",
                                    atualizar=True)
    cliente_mock.fechar.assert_called_once()
    assert r == {"registrados": 1}
