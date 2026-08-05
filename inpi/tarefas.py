"""Tarefas leves do escritorio (docs/plano-v2.md 4.7).

NAO e docketing: sem calculo de prazo legal, sem regra de LPI. 'prazo_interno'
e uma data livre que o operador digita como lembrete -- nada aqui deriva de
inpi/prazos.py. Mesmo banco de carteira.py (carteira.duckdb), tabela propria.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import duckdb

from inpi.carteira import BANCO

ESQUEMA = """
CREATE SEQUENCE IF NOT EXISTS tarefas_id_seq START 1;
CREATE TABLE IF NOT EXISTS tarefas (
    id             INTEGER PRIMARY KEY DEFAULT nextval('tarefas_id_seq'),
    processo       VARCHAR,
    descricao      VARCHAR NOT NULL,
    prazo_interno  DATE,
    status         VARCHAR NOT NULL DEFAULT 'aberta',
    criado_em      TIMESTAMP NOT NULL DEFAULT current_timestamp,
    concluido_em   TIMESTAMP
)
"""

_ORIGEM = "lembrete interno, não é prazo legal (não é docketing)"


def con(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    BANCO.parent.mkdir(parents=True, exist_ok=True)
    c = duckdb.connect(str(BANCO), read_only=read_only)
    if not read_only:
        c.execute(ESQUEMA)
    return c


def tarefa_criar(descricao: str, processo: str | None = None,
                  prazo_interno: str | None = None) -> dict:
    """Cria um lembrete interno. NAO calcula prazo legal -- 'prazo_interno' e a
    data que o operador digitou, sem regra de LPI por tras."""
    c = con()
    try:
        row = c.execute(
            "INSERT INTO tarefas (processo, descricao, prazo_interno) "
            "VALUES (?, ?, ?) RETURNING id",
            [processo, descricao, prazo_interno],
        ).fetchone()
    finally:
        c.close()
    return {"id": row[0], "origem": _ORIGEM}


def tarefa_listar(processo: str | None = None, status: str = "aberta") -> dict:
    """Lista tarefas. status='todas' devolve abertas e concluidas."""
    if not BANCO.exists():
        return {"lista": [], "origem": _ORIGEM}
    c = con(read_only=True)
    try:
        clausulas, params = [], []
        if status != "todas":
            clausulas.append("status = ?")
            params.append(status)
        if processo:
            clausulas.append("processo = ?")
            params.append(processo)
        where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
        cols = ["id", "processo", "descricao", "prazo_interno", "status",
                "criado_em", "concluido_em"]
        linhas = c.execute(
            f"SELECT {', '.join(cols)} FROM tarefas {where} "
            "ORDER BY prazo_interno NULLS LAST, id", params,
        ).fetchall()
    finally:
        c.close()
    return {"lista": [dict(zip(cols, l)) for l in linhas], "origem": _ORIGEM}


def tarefa_concluir(id: int) -> dict:
    """Marca a tarefa como concluida (concluido_em = agora)."""
    c = con()
    try:
        row = c.execute(
            "UPDATE tarefas SET status = 'concluida', concluido_em = current_timestamp "
            "WHERE id = ? AND status != 'concluida' RETURNING id",
            [id],
        ).fetchone()
    finally:
        c.close()
    if row is None:
        return {"ok": False, "erro": f"tarefa {id} nao encontrada ou ja concluida"}
    return {"ok": True, "id": id, "origem": _ORIGEM}


def tarefas_vencendo(dias: int = 7, hoje: str | None = None) -> list[dict]:
    """Tarefas abertas com prazo_interno dentro da janela de N dias (inclui
    vencidas). Usada pelo dashboard -- nao e um vigia novo, so um recorte
    direto da tabela (tarefa leve nao justifica pacote de vigilancia)."""
    ref = date.fromisoformat(hoje) if hoje else date.today()
    limite = (ref + timedelta(days=dias)).isoformat()
    if not BANCO.exists():
        return []
    r = tarefa_listar(status="aberta")
    return [t for t in r["lista"]
            if t["prazo_interno"] is not None and str(t["prazo_interno"]) <= limite]


def demo() -> None:
    import tempfile
    from pathlib import Path
    global BANCO
    orig = BANCO
    with tempfile.TemporaryDirectory() as d:
        BANCO = Path(d) / "carteira.duckdb"
        try:
            r = tarefa_criar("responder oficio", processo="BR102022010731",
                              prazo_interno="2026-08-10")
            tid = r["id"]
            assert tarefa_listar()["lista"][0]["id"] == tid
            venc = tarefas_vencendo(dias=7, hoje="2026-08-05")
            assert len(venc) == 1
            assert tarefa_concluir(tid)["ok"] is True
            assert tarefa_listar()["lista"] == []
            assert tarefa_concluir(999)["ok"] is False
        finally:
            BANCO = orig
    print("OK")


if __name__ == "__main__":
    demo()
