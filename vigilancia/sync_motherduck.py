"""Sobe o banco INPI local para o MotherDuck apos a ingestao semanal.

Sem isto o agente do Teams responde com dados congelados. Roda como passo
final de vigilancia.executar -- e NUNCA pode derrubar a ingestao local: falha
aqui e logada e devolvida, nao propagada.

O que sobe e o que nao sobe (decisao, nao esquecimento):
- `inpi` (inpi.duckdb): substituicao COMPLETA -- so a ingestao local escreve.
- `carteira` (tarefas/radar_watermark): NAO sincroniza. O agente remoto cria
  tarefas direto na nuvem; sobrescrever com o local apagaria essas tarefas.
  (A antiga tabela `casos`/carteira ingerida foi removida na Fase G.)
- `landscape_cache`: nao sincroniza. O cache remoto vive e cresce na nuvem.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from dotenv import load_dotenv

from inpi.db import BANCO as BANCO_INPI
from inpi.ingest import PROCURADORES_SIGILO
from inpi.ingest import TABELAS as TABELAS_BASE

# Task Scheduler nao herda o .env -- carrega aqui, como epo/epo_mcp.py faz.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Copia da rodada anterior, deixada por vigilancia.reingestao.reingerir() ANTES
# de ingest.main() apagar e recriar o .duckdb. E contra ela que o diff roda.
BANCO_ANTERIOR = BANCO_INPI.with_name("inpi_anterior.duckdb")

# Resultado do ULTIMO sync. Existe porque vigilancia.reingestao apaga e recria
# inpi_anterior.duckdb toda semana, com sync bem-sucedido ou nao: sem este
# marcador, um sync que falhou no meio (remoto ja parcialmente alterado) fazia
# a rodada seguinte diffar contra a base errada e o MotherDuck derivava em
# silencio pra sempre. Sync anterior nao-ok => reconstrucao completa.
STATUS_SYNC = Path(__file__).resolve().parent / "data" / "ultimo_sync_status.json"

# Tabelas derivadas (materializadas por inpi/ingest.py a partir das de cima) que
# tambem precisam ir para o MotherDuck -- sem elas o agente remoto perde
# titular/escritorio resolvidos e a ficha-extras.
TABELAS_DERIVADAS = ("titulares", "escritorios", "identidade_escritorio",
                     "ficha_extras", "ficha_peticoes", "ficha_anuidades")


def _registra_status(r: dict) -> dict:
    """Grava o desfecho do sync e devolve o proprio resultado (para usar em
    `return _registra_status({...})`). Sync pulado por falta de token nao
    conta como falha -- nada foi tocado no remoto, o estado anterior segue
    valendo."""
    if r.get("pulado"):
        return r
    STATUS_SYNC.parent.mkdir(parents=True, exist_ok=True)
    STATUS_SYNC.write_text(json.dumps({
        "ok": bool(r.get("ok")),
        "quando": datetime.now(timezone.utc).isoformat(),
        "mensagem": r.get("mensagem", ""),
    }, ensure_ascii=False), encoding="utf-8")
    return r


def _ultimo_sync_ok() -> bool:
    """True quando nao ha registro (primeira rodada -- nada a desconfiar) ou o
    ultimo sync terminou ok."""
    if not STATUS_SYNC.exists():
        return True
    try:
        return bool(json.loads(STATUS_SYNC.read_text(encoding="utf-8")).get("ok"))
    except (json.JSONDecodeError, OSError):
        return False  # marcador ilegivel: assume o pior e reconstroi


def sincronizar() -> dict:
    """Sobe inpi (completo) para o MotherDuck. Nunca levanta: devolve
    {"ok": bool, ...} para o chamador logar."""
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if not token:
        return {"ok": False, "pulado": True,
                "mensagem": "MOTHERDUCK_TOKEN ausente -- sync pulado."}
    try:
        con = duckdb.connect(f"md:?motherduck_token={token}")
        try:
            enviados = []
            if BANCO_INPI.exists():
                caminho = str(BANCO_INPI).replace("'", "''")
                con.execute(f"CREATE OR REPLACE DATABASE inpi FROM '{caminho}'")
                enviados.append("inpi (completo)")
            return _registra_status({"ok": True, "enviados": enviados})
        finally:
            con.close()
    except Exception as exc:  # rede/MotherDuck fora: loga, nao derruba a ingestao
        return _registra_status({"ok": False, "mensagem": f"{type(exc).__name__}: {exc}"})


def _colunas(con: duckdb.DuckDBPyConnection, tabela: str) -> list[str]:
    return [r[0] for r in con.execute(f"DESCRIBE {tabela}").fetchall()]


def _existe_tabela(con: duckdb.DuckDBPyConnection, catalogo: str, tabela: str) -> bool:
    r = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_catalog = ? AND table_name = ?",
        [catalogo, tabela],
    ).fetchone()
    return r is not None


def _diff_tabela(con: duckdb.DuckDBPyConnection, tabela: str) -> dict:
    """Sobe em `remoto.<tabela>` so a diferenca entre `antigo.<tabela>` (estado
    da rodada passada, anexado read-only) e `<tabela>` (estado atual, recem-
    ingerido, banco default da conexao).

    Diferenca de LINHA INTEIRA (EXCEPT), nao por chave: ingest.py ja faz
    SELECT DISTINCT em toda tabela, entao nao ha duas linhas fisicamente
    iguais numa mesma tabela -- EXCEPT enxerga corretamente insercao, remocao
    E alteracao (uma linha que mudou sai como "removida" a antiga + "inserida"
    a nova, sem precisar declarar chave primaria por tabela).
    """
    cols = ", ".join(_colunas(con, tabela))
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE _add AS "
        f"SELECT {cols} FROM {tabela} EXCEPT SELECT {cols} FROM antigo.{tabela}"
    )
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE _rem AS "
        f"SELECT {cols} FROM antigo.{tabela} EXCEPT SELECT {cols} FROM {tabela}"
    )
    n_add = con.execute("SELECT count(*) FROM _add").fetchone()[0]
    n_rem = con.execute("SELECT count(*) FROM _rem").fetchone()[0]
    if n_rem:
        colunas = _colunas(con, tabela)
        # IS NOT DISTINCT FROM (nao '='): varias colunas aceitam NULL
        # (ex.: procurador de pedido antigo), e '=' contra NULL nunca bate.
        casamento = " AND ".join(f"t.{c} IS NOT DISTINCT FROM r.{c}" for c in colunas)
        con.execute(f"DELETE FROM remoto.{tabela} AS t USING _rem AS r WHERE {casamento}")
    if n_add:
        con.execute(f"INSERT INTO remoto.{tabela} SELECT {cols} FROM _add")
    con.execute("DROP TABLE _add")
    con.execute("DROP TABLE _rem")
    return {"tabela": tabela, "inseridos": n_add, "removidos": n_rem}


def sincronizar_incremental() -> dict:
    """Sobe pro MotherDuck so a diferenca desde a ultima ingestao, em vez de
    reenviar o banco inteiro (1,2 GB) toda semana -- e o que sincronizar()
    completo faz, e o que girava horas de upload numa rede domestica.

    Cai para sincronizar() completo quando:
      - nao ha inpi_anterior.duckdb pra comparar (primeira vez, ou a rodada
        anterior nao deixou copia por algum motivo) -- sem base, nao ha diff
        possivel, so reconstrucao total mesmo;
      - o ULTIMO sync registrado (STATUS_SYNC) nao terminou ok. Ai o remoto
        esta num estado desconhecido (o diff daquela rodada pode ter aplicado
        metade dos DELETE/INSERT) e o inpi_anterior.duckdb que existe e o da
        reingestao desta semana, nao o baseline que o remoto reflete --
        diffar contra ele faria o remoto derivar em silencio;
      - qualquer tabela nao existir ainda no remoto ou na copia antiga (schema
        novo) -- sobe essa tabela inteira via CREATE OR REPLACE, sem tentar
        diff contra o que nao existe.

    Se QUALQUER erro no meio (rede, coluna incompativel etc.), devolve
    ok=False sem propagar -- mesma regra do resto deste modulo, e o desfecho
    fica gravado em STATUS_SYNC para a proxima rodada reconstruir do zero.
    """
    if not BANCO_ANTERIOR.exists():
        r = sincronizar()
        r["modo"] = "completo (sem copia anterior para comparar)"
        return r
    if not _ultimo_sync_ok():
        r = sincronizar()
        r["modo"] = "completo (sync anterior falhou -- baseline nao confiavel)"
        return r

    token = os.environ.get("MOTHERDUCK_TOKEN")
    if not token:
        return {"ok": False, "pulado": True,
                "mensagem": "MOTHERDUCK_TOKEN ausente -- sync pulado."}
    if not BANCO_INPI.exists():
        return _registra_status(
            {"ok": False, "mensagem": "inpi.duckdb novo nao existe -- rode a ingestao antes."})

    try:
        con = duckdb.connect(str(BANCO_INPI))
    except Exception as exc:
        return _registra_status({"ok": False, "mensagem": f"{type(exc).__name__}: {exc}"})

    try:
        antigo = str(BANCO_ANTERIOR).replace("'", "''")
        con.execute(f"ATTACH '{antigo}' AS antigo (READ_ONLY)")
        # 'md:inpi?motherduck_token=...' so funciona como STRING DE CONEXAO
        # (duckdb.connect), nao como alvo de ATTACH -- ali o driver le a query
        # string como parte do nome do catalogo e devolve "no database/share
        # named 'inpi?motherduck_token=...'". 'SET motherduck_token=' tambem
        # nao existe como parametro de configuracao (testado, CatalogException).
        # O que funciona pra anexar por NOME dentro de uma conexao ja aberta
        # (preciso aqui: a conexao default e o .duckdb local novo) e so
        # ATTACH 'md:inpi' -- a extensao le MOTHERDUCK_TOKEN do ambiente
        # sozinha, e load_dotenv() no topo deste modulo ja garante que a
        # variavel esta no processo antes de qualquer conexao.
        con.execute("ATTACH 'md:inpi' AS remoto")

        tabelas_novo = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        resultados = []
        for tabela in (*TABELAS_BASE, *TABELAS_DERIVADAS):
            if tabela not in tabelas_novo:
                continue  # tabela derivada que essa rodada nao gerou (ex.: sem ficha-extras.csv)
            if not _existe_tabela(con, "antigo", tabela) or not _existe_tabela(con, "remoto", tabela):
                con.execute(f"CREATE OR REPLACE TABLE remoto.{tabela} AS SELECT * FROM {tabela}")
                resultados.append({"tabela": tabela, "modo": "completa (tabela nova)"})
                continue
            resultados.append(_diff_tabela(con, tabela))
    except Exception as exc:
        con.close()
        return _registra_status({"ok": False, "mensagem": f"{type(exc).__name__}: {exc}"})

    con.close()
    BANCO_ANTERIOR.unlink(missing_ok=True)
    return _registra_status({"ok": True, "modo": "incremental", "tabelas": resultados})


def sincronizar_sigilo_incremental() -> dict:
    """Sobe SO as linhas curadas de procuradores-sigilo.csv para o MotherDuck,
    sem reenviar o banco inteiro (1,2 GB).

    Espelha exatamente o merge de inpi.ingest._mescla_procuradores_sigilo, mas
    contra a copia remota: insere em `procuradores` apenas os numero_inpi que
    (a) existem em `biblio` remoto e (b) ainda NAO tem procurador remoto. E
    idempotente -- rodar duas vezes nao duplica. A tabela `escritorios` NAO
    precisa mudar: as grafias coletadas ja sao grafias oficiais da firma, ja
    presentes em `escritorios` remoto (o join escritorios.original = procurador
    ja as resolve para a chave canonica).

    Use quando so a coleta de sigilo mudou; para reconstrucao completa da base
    (ingestao semanal), use sincronizar(). Nunca levanta."""
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if not token:
        return {"ok": False, "pulado": True,
                "mensagem": "MOTHERDUCK_TOKEN ausente -- sync pulado."}
    if not PROCURADORES_SIGILO.exists():
        return {"ok": True, "inseridos": 0, "mensagem": "sem CSV curado."}
    try:
        con = duckdb.connect(f"md:?motherduck_token={token}")
        try:
            con.execute("USE inpi")
            antes = con.execute("SELECT count(*) FROM procuradores").fetchone()[0]
            con.execute(f"""
              CREATE OR REPLACE TEMP TABLE _sigilo_curado AS
              SELECT * FROM read_csv('{PROCURADORES_SIGILO.as_posix()}', header=true,
                                      delim=',', quote='"', escape='"',
                                      columns={{
                                        'numero_inpi': 'VARCHAR', 'procurador': 'VARCHAR',
                                        'escritorio_canonico': 'VARCHAR', 'fonte': 'VARCHAR',
                                        'coletado_em': 'VARCHAR', 'observacao': 'VARCHAR'
                                      }})
            """)
            con.execute("""
              INSERT INTO procuradores
                (codigo_interno, numero_inpi, procurador,
                 cgccpfprocurador, tipopessoaprocurador, data_inicio_procurador)
              SELECT b.codigo_interno, s.numero_inpi, s.procurador, NULL, NULL, NULL
              FROM _sigilo_curado s
              JOIN biblio b USING (numero_inpi)
              WHERE s.numero_inpi NOT IN (SELECT numero_inpi FROM procuradores)
            """)
            depois = con.execute("SELECT count(*) FROM procuradores").fetchone()[0]
            return {"ok": True, "inseridos": depois - antes}
        finally:
            con.close()
    except Exception as exc:
        return {"ok": False, "mensagem": f"{type(exc).__name__}: {exc}"}


if __name__ == "__main__":
    print(sincronizar_sigilo_incremental())
