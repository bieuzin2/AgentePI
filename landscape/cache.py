"""Cache local das consultas BigQuery em DuckDB (plano-v2 4.6, 3): poupa quota
do free tier (1 TB/mes) reusando resultado de consulta identica por 30 dias.

Padrao simples proposital: uma tabela, chave = hash da funcao + argumentos.
Nao existe cache generico no projeto pra reusar (INPI/EPO cacheiam de outro
jeito -- DuckDB de dados abertos e dogpile.cache respectivamente), entao isto
fica o minimo necessario, sem virar biblioteca.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent
BANCO = RAIZ / "data" / "landscape_cache.duckdb"
TTL_DIAS = 30

_con: duckdb.DuckDBPyConnection | None = None
# True quando o arquivo local esta travado por outro processo e caimos para leitura:
# servimos o cache assim mesmo, mas salvar() vira no-op (nao da para escrever).
_somente_leitura = False


def _conectar() -> duckdb.DuckDBPyConnection:
    global _con, _somente_leitura
    if _con is None:
        _somente_leitura = False  # recomputa a cada conexao nova; so a falha de lock liga
        token = os.environ.get("MOTHERDUCK_TOKEN")
        if token:
            # MotherDuck (produção): sem lock de arquivo local, escrita concorrente ok.
            _con = duckdb.connect(f"md:?motherduck_token={token}")
            _con.execute("CREATE DATABASE IF NOT EXISTS landscape_cache")
            _con.execute("USE landscape_cache")
            _garantir_esquema(_con)
        else:
            BANCO.parent.mkdir(parents=True, exist_ok=True)
            try:
                _con = duckdb.connect(str(BANCO))
                _garantir_esquema(_con)
            except Exception:
                # DuckDB local e single-writer: se outro processo (outro servidor MCP,
                # um orfao) segura o arquivo em escrita, abrir RW falha. Em vez de
                # derrubar TODA consulta de landscape, caimos para leitura -- o cache
                # ainda serve o que ja esta gravado; salvar() vira no-op ate o writer
                # soltar. Se o arquivo nem existe, o erro e outro: propaga.
                if not BANCO.exists():
                    raise
                _con = duckdb.connect(str(BANCO), read_only=True)
                _somente_leitura = True
    return _con


def _garantir_esquema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS landscape_cache ("
        "chave VARCHAR PRIMARY KEY, resultado VARCHAR, criado_em TIMESTAMP)"
    )
    colunas = {row[1] for row in con.execute(
        "PRAGMA table_info('landscape_cache')").fetchall()}
    if "nome_consulta" not in colunas:
        con.execute("ALTER TABLE landscape_cache ADD COLUMN nome_consulta VARCHAR")


def _chave(nome_consulta: str, args: dict) -> str:
    bruto = nome_consulta + json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def obter(nome_consulta: str, args: dict) -> dict | None:
    """Resultado em cache se existir e ainda estiver dentro do TTL, senao None."""
    con = _conectar()
    linha = con.execute(
        "SELECT resultado, criado_em FROM landscape_cache WHERE chave = ?",
        [_chave(nome_consulta, args)],
    ).fetchone()
    if linha is None:
        return None
    resultado_json, criado_em = linha
    if datetime.now(timezone.utc) - criado_em.replace(tzinfo=timezone.utc) > timedelta(days=TTL_DIAS):
        return None
    return json.loads(resultado_json)


def salvar(nome_consulta: str, args: dict, resultado: dict) -> None:
    con = _conectar()
    if _somente_leitura:
        return  # cache aberto em modo leitura (arquivo travado): nao grava, nao derruba
    try:
        con.execute(
            "INSERT OR REPLACE INTO landscape_cache VALUES (?, ?, ?, ?)",
            [_chave(nome_consulta, args), json.dumps(resultado, default=str),
             datetime.now(timezone.utc), nome_consulta],
        )
    except Exception:
        # Falha de escrita (lock adquirido depois da conexao, disco cheio) nao pode
        # derrubar a consulta que ja rodou -- o cache e otimizacao, nao fonte de verdade.
        pass


def demo() -> None:
    """Self-check contra banco temporario: salva, le de volta, TTL vencido some."""
    import tempfile

    global _con, BANCO, _somente_leitura
    _con = None
    _somente_leitura = False
    with tempfile.TemporaryDirectory() as tmp:
        BANCO = Path(tmp) / "cache.duckdb"
        assert obter("teste", {"x": 1}) is None
        salvar("teste", {"x": 1}, {"linhas": [1, 2]})
        assert obter("teste", {"x": 1}) == {"linhas": [1, 2]}
        assert obter("teste", {"x": 2}) is None
    print("OK  cache grava, le e distingue por argumento")


if __name__ == "__main__":
    demo()
