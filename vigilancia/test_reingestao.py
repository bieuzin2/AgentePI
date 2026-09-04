"""Testa so o comportamento novo: o .duckdb existente vira inpi_anterior.duckdb
ANTES de ingest.main() rodar. O resto (baixar/main de verdade) e coberto pelo
uso real da vigilancia semanal, nao aqui -- baixar 1,9 GB em teste seria
absurdo."""

from __future__ import annotations

from unittest.mock import patch

import vigilancia.reingestao as reingestao


def test_preserva_banco_anterior_antes_de_recriar(monkeypatch, tmp_path):
    banco = tmp_path / "inpi.duckdb"
    banco.write_bytes(b"banco da semana passada")
    anterior = tmp_path / "inpi_anterior.duckdb"
    monkeypatch.setattr(reingestao.ingest, "BANCO", banco)
    monkeypatch.setattr(reingestao, "BANCO_ANTERIOR", anterior)
    monkeypatch.setattr(reingestao, "CORTE", tmp_path / "ultima_reingestao.json")

    with patch.object(reingestao.ingest, "main", return_value=0) as main:
        reingestao.reingerir(baixar=False)

    main.assert_called_once()
    assert not banco.exists()  # ingest.main() e quem recria; aqui so garantimos o rename antes
    assert anterior.read_bytes() == b"banco da semana passada"


def test_sem_banco_previo_nao_quebra(monkeypatch, tmp_path):
    banco = tmp_path / "inpi.duckdb"  # nao existe
    monkeypatch.setattr(reingestao.ingest, "BANCO", banco)
    monkeypatch.setattr(reingestao, "BANCO_ANTERIOR", tmp_path / "inpi_anterior.duckdb")
    monkeypatch.setattr(reingestao, "CORTE", tmp_path / "ultima_reingestao.json")

    with patch.object(reingestao.ingest, "main", return_value=0) as main:
        r = reingestao.reingerir(baixar=False)

    main.assert_called_once()
    assert not r.get("erro")


def test_descarta_anterior_obsoleto_de_rodada_que_falhou_antes_do_sync(monkeypatch, tmp_path):
    """Se uma rodada anterior deixou inpi_anterior.duckdb (ex.: o sync falhou
    antes de consumi-lo e apagar), a proxima reingestao NAO deve empilhar por
    cima -- descarta o obsoleto e guarda so a geracao mais recente.

    Quem protege o MotherDuck de diffar contra esse baseline errado NAO e este
    modulo, e sync_motherduck.STATUS_SYNC: sync anterior nao-ok => aquela
    rodada reconstroi o remoto inteiro em vez de confiar no incremental
    (ver test_incremental_apos_falha_forca_reconstrucao_completa)."""
    banco = tmp_path / "inpi.duckdb"
    banco.write_bytes(b"semana atual")
    anterior = tmp_path / "inpi_anterior.duckdb"
    anterior.write_bytes(b"duas semanas atras, obsoleto")
    monkeypatch.setattr(reingestao.ingest, "BANCO", banco)
    monkeypatch.setattr(reingestao, "BANCO_ANTERIOR", anterior)
    monkeypatch.setattr(reingestao, "CORTE", tmp_path / "ultima_reingestao.json")

    with patch.object(reingestao.ingest, "main", return_value=0):
        reingestao.reingerir(baixar=False)

    assert anterior.read_bytes() == b"semana atual"
