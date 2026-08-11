"""Roda coleta_sigilo em rodadas ate convergir, para um escritorio canonico.

Cada rodada: gera a lista de sigilosos-sem-procurador de clientes ja ligados
ao escritorio, varre em paralelo, mescla no banco (ingest.py). Descobrir um
novo cliente (titular que so aparece porque um sigiloso dele bateu com o
escritorio nesta rodada) expande a lista de candidatos da PROXIMA rodada --
por isso convergencia precisa de mais de uma passada, nao e bug.

Para quando: sem candidatos novos, poucos registros na rodada (retorno
decrescente), ou limite de rodadas atingido.

Rode: python scripts/coleta_sigilo_rodadas.py [escritorio] [max_rodadas]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import inpi.db as dbmod  # noqa: E402
from inpi.coleta_sigilo import varrer_e_registrar_paralelo  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
MIN_REGISTROS_PARA_CONTINUAR = 5


def _candidatos(escritorio_canonico: str) -> list[str]:
    linhas = dbmod.con().execute(
        """
        WITH titular_chave AS (
            SELECT dp.numero_inpi, t.chave
            FROM depositantes dp JOIN titulares t ON t.original = dp.depositante
            GROUP BY dp.numero_inpi, t.chave
        ),
        clientes AS (
            SELECT DISTINCT t.chave
            FROM procuradores p
            JOIN escritorios e ON e.original = p.procurador
            JOIN depositantes dp ON dp.numero_inpi = p.numero_inpi
            JOIN titulares t ON t.original = dp.depositante
            WHERE e.chave = ?
        )
        SELECT DISTINCT b.numero_inpi
        FROM biblio b
        JOIN titular_chave tc USING (numero_inpi)
        LEFT JOIN procuradores p USING (numero_inpi)
        WHERE b.sigilo = 1 AND p.numero_inpi IS NULL
          AND tc.chave IN (SELECT chave FROM clientes)
        ORDER BY b.data_deposito DESC
        """,
        [escritorio_canonico],
    ).fetchall()
    return [r[0] for r in linhas]


def rodar(escritorio_canonico: str, max_rodadas: int = 8, paralelismo: int = 6) -> None:
    for rodada in range(1, max_rodadas + 1):
        candidatos = _candidatos(escritorio_canonico)
        print(f"\n=== rodada {rodada}: {len(candidatos)} candidatos ===", flush=True)
        if not candidatos:
            print("sem candidatos -- convergiu.", flush=True)
            break

        resumo = varrer_e_registrar_paralelo(candidatos, escritorio_canonico, paralelismo=paralelismo)
        print(f"rodada {rodada} resumo: {resumo}", flush=True)
        if "erro" in resumo:
            print("sessao anonima falhou, parando.", flush=True)
            break

        subprocess.run([sys.executable, str(RAIZ / "inpi" / "ingest.py")], check=True, cwd=RAIZ)
        dbmod._con = None  # forca reabrir o banco recem-reconstruido na proxima rodada

        if resumo["registrados"] < MIN_REGISTROS_PARA_CONTINUAR:
            print(f"so {resumo['registrados']} registros nesta rodada -- retorno "
                  "decrescente, parando.", flush=True)
            break


if __name__ == "__main__":
    escritorio = sys.argv[1] if len(sys.argv) > 1 else "CLARKE MODET"
    max_rodadas = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    rodar(escritorio, max_rodadas)
