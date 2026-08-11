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

import os
from pathlib import Path

import duckdb
from dotenv import load_dotenv

from inpi.db import BANCO as BANCO_INPI
from inpi.ingest import PROCURADORES_SIGILO

# Task Scheduler nao herda o .env -- carrega aqui, como epo/epo_mcp.py faz.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


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
            return {"ok": True, "enviados": enviados}
        finally:
            con.close()
    except Exception as exc:  # rede/MotherDuck fora: loga, nao derruba a ingestao
        return {"ok": False, "mensagem": f"{type(exc).__name__}: {exc}"}


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
