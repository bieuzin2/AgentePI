"""Reingestao semanal: baixa os CSVs do INPI e recarrega o DuckDB local.

So um wrapper fino sobre inpi/ingest.py (baixar + main), que ja faz download
atomico e recriacao do banco do zero. As duas coisas novas aqui: (1) registrar
a data de corte usada pela vigilancia, para os vigias saberem "desde quando";
(2) preservar o banco da rodada anterior como inpi_anterior.duckdb ANTES de
ingest.main() apagar e recriar o .duckdb -- e contra essa copia que
sync_motherduck.sincronizar_incremental() calcula o diff linha-a-linha, para
subir ao MotherDuck so o que mudou em vez do banco inteiro (1,2 GB) toda
semana.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

from inpi import ingest

RAIZ = Path(__file__).resolve().parent
CORTE = RAIZ / "data" / "ultima_reingestao.json"
BANCO_ANTERIOR = ingest.BANCO.with_name("inpi_anterior.duckdb")


def reingerir(baixar: bool = True) -> dict:
    """Baixa (opcional) e recarrega a base. Devolve a data de corte registrada.

    Se `baixar=False`, so recarrega o DuckDB a partir do que ja estiver em
    inpi/data/raw/ -- util para testes offline.
    """
    if baixar:
        if ingest.baixar() != 0:
            return {"erro": True, "mensagem": "Falha ao baixar CSVs do INPI."}
    if ingest.BANCO.exists():
        # so guarda 1 geracao: se uma rodada anterior ja deixou um
        # inpi_anterior.duckdb sem o sync ter rodado (ou ter falhado antes de
        # consumi-lo), ele fica obsoleto -- descarta em favor do mais recente.
        BANCO_ANTERIOR.unlink(missing_ok=True)
        ingest.BANCO.rename(BANCO_ANTERIOR)
    if ingest.main() != 0:
        return {"erro": True, "mensagem": "Falha ao recarregar o DuckDB."}

    CORTE.parent.mkdir(parents=True, exist_ok=True)
    registro = {
        "executado_em": datetime.now(timezone.utc).isoformat(),
        "data": date.today().isoformat(),
    }
    CORTE.write_text(json.dumps(registro, ensure_ascii=False), encoding="utf-8")
    return registro


def ultima_reingestao() -> dict | None:
    """Data/hora da ultima reingestao registrada, ou None se nunca rodou."""
    if not CORTE.exists():
        return None
    return json.loads(CORTE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    t0 = time.time()
    print(json.dumps(reingerir(), ensure_ascii=False, indent=2))
    print(f"{time.time() - t0:.1f}s")
