"""Descobre os maiores clientes da Clarke Modet na base INPI e gera o rascunho
de referencias curadas (plano de refinamento, Fase A1).

Saida (para REVISAO HUMANA antes de valer como 'curado'):
  inpi/referencias/clientes-clarke.csv       chave_canonica,nome_exibicao,processos,grafias
  inpi/referencias/titulares-apelidos.csv    variante,canonico,processos,revisado_por,data,nota
                                             (so linhas rascunho, coluna revisado_por vazia)

A chave canonica vem da tabela `titulares` (3 camadas: raiz CNPJ > heranca >
nome normalizado -- inpi/ingest.py::_materializa_titulares). Nao inventamos
outra normalizacao aqui.

Rode: python scripts/descobrir_clientes.py [top_n]
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inpi.db import con  # noqa: E402

REFERENCIAS = Path(__file__).resolve().parents[1] / "inpi" / "referencias"

CHAVE_CLARKE = "CLARKE MODET"


def descobrir(top_n: int = 20) -> list[dict]:
    """Top-N titulares (chave canonica) dos processos onde a Clarke Modet e
    procuradora, com todas as grafias agrupadas por chave."""
    linhas = con().execute(
        """
        WITH cm AS (
          SELECT DISTINCT p.numero_inpi
          FROM procuradores p JOIN escritorios e ON e.original = p.procurador
          WHERE e.chave = ?
        )
        SELECT t.chave,
               count(DISTINCT dp.numero_inpi) AS processos,
               count(DISTINCT dp.depositante) AS grafias,
               arg_max(dp.depositante, dp.numero_inpi) AS exemplo,
               list(DISTINCT dp.depositante) AS todas_grafias
        FROM depositantes dp
        JOIN titulares t ON t.original = dp.depositante
        JOIN cm USING (numero_inpi)
        GROUP BY t.chave
        ORDER BY processos DESC
        LIMIT ?
        """,
        [CHAVE_CLARKE, top_n],
    ).fetchall()
    cols = ["chave", "processos", "grafias", "exemplo", "todas_grafias"]
    return [dict(zip(cols, l)) for l in linhas]


def gravar(clientes: list[dict]) -> None:
    REFERENCIAS.mkdir(exist_ok=True)

    with (REFERENCIAS / "clientes-clarke.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["chave_canonica", "nome_exibicao", "processos", "grafias"])
        for c in clientes:
            w.writerow([c["chave"], c["exemplo"], c["processos"], c["grafias"]])

    # Rascunho de apelidos: cada grafia distinta do cliente vira candidata a
    # revisao. A chave ja agrupa; o CSV existe para o humano confirmar/emendar
    # e para receber depois a lista oficial do escritorio.
    destino = REFERENCIAS / "titulares-apelidos.csv"
    if destino.exists():
        print(f"AVISO: {destino.name} ja existe -- nao sobrescrevo curadoria. "
              "Apague manualmente se quiser regerar o rascunho.")
        return
    with destino.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["variante", "canonico", "processos", "revisado_por", "data", "nota"])
        for c in clientes:
            for g in sorted(set(c["todas_grafias"])):
                w.writerow([g, c["chave"], c["processos"], "", "", "rascunho automatico"])


def main() -> None:
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    clientes = descobrir(top_n)
    if not clientes:
        raise SystemExit("Nenhum processo com Clarke Modet como procuradora -- "
                         "confira a chave e a base.")
    gravar(clientes)
    print(f"{'chave':<45} {'proc':>6} {'grafias':>7}")
    for c in clientes:
        print(f"{c['chave']:<45} {c['processos']:>6} {c['grafias']:>7}  {c['exemplo'][:40]}")
    print(f"\nGravados clientes-clarke.csv e titulares-apelidos.csv (rascunho) "
          f"em {REFERENCIAS} -- REVISAR antes de considerar curado.")


if __name__ == "__main__":
    main()
