"""Valida a plataforma nova (Modulo de Servicos de Patentes) contra uma
amostra de processos ja cobertos pelo pePI, ANTES de desligar o pePI+Tor
(ver docs/superpowers/specs/2026-09-04-inpi-plataforma-nova-design.md,
Stream A). Mede taxa de erro e cobertura de depositos recentes -- hipotese a
testar: a plataforma nova pode nao ter indexado ainda pedidos depositados
nos ultimos dias/semanas (o pePI, sistema legado de tramitacao, teria).

Rode manualmente: python -m inpi.validar_plataforma_nova
Precisa de INPI_PAG_LOGIN/INPI_PAG_PASSWORD no .env -- rede real, conta
dedicada, NAO roda em teste automatizado.
"""

from __future__ import annotations

import random
import time
from datetime import date, timedelta

from inpi.consulta import _linhas
from inpi.plataforma_nova import ClientePlataformaNova, PlataformaNovaError


def amostrar_processos(escritorio_canonico: str | None, tamanho: int,
                       dias_recentes: int) -> list[dict]:
    """Amostra numero_inpi ja coletados pelo pePI (tabela ficha_extras), ate
    metade de `tamanho` de cada grupo -- 'recentes' (deposito nos ultimos
    `dias_recentes` dias) e 'antigos' -- pra medir cobertura das duas
    populacoes separadamente, nao so uma media que esconde o problema."""
    corte = (date.today() - timedelta(days=dias_recentes)).isoformat()
    filtro = " AND fe.escritorio_canonico = ?" if escritorio_canonico else ""
    params_extra = [escritorio_canonico] if escritorio_canonico else []

    # strftime antes de comparar, nao DATE bruto contra parametro VARCHAR --
    # mesmo padrao de inpi/anuidades_pagas.py (comparar DATE ao ? direto e
    # ambiguo pro driver duckdb quando o parametro chega como str do Python).
    recentes = _linhas(
        f"""SELECT fe.numero_inpi, b.data_deposito
            FROM ficha_extras fe JOIN biblio b USING (numero_inpi)
            WHERE strftime(b.data_deposito, '%Y-%m-%d') >= ?{filtro}""",
        [corte, *params_extra],
    )
    antigos = _linhas(
        f"""SELECT fe.numero_inpi, b.data_deposito
            FROM ficha_extras fe JOIN biblio b USING (numero_inpi)
            WHERE strftime(b.data_deposito, '%Y-%m-%d') < ?{filtro}""",
        [corte, *params_extra],
    )
    metade = max(1, tamanho // 2)
    amostra = (random.sample(recentes, min(metade, len(recentes)))
              + random.sample(antigos, min(metade, len(antigos))))
    for item in amostra:
        item["recente"] = str(item["data_deposito"]) >= corte
    return amostra


def montar_relatorio(resultados: list[dict]) -> dict:
    """Agrega o resultado por-processo em taxas. Cada item de `resultados`:
    {numero_inpi, recente, sucesso, indexado, erro}."""
    def _taxa(grupo: list[dict]) -> dict:
        total = len(grupo)
        if total == 0:
            return {"total": 0, "sucesso": 0, "indexado": 0,
                    "taxa_sucesso": None, "taxa_indexado": None}
        sucesso = sum(1 for r in grupo if r["sucesso"])
        indexado = sum(1 for r in grupo if r.get("indexado"))
        return {"total": total, "sucesso": sucesso, "indexado": indexado,
                "taxa_sucesso": round(sucesso / total, 3),
                "taxa_indexado": round(indexado / total, 3)}

    recentes = [r for r in resultados if r["recente"]]
    antigos = [r for r in resultados if not r["recente"]]
    return {
        "total_amostrado": len(resultados),
        "recentes": _taxa(recentes),
        "antigos": _taxa(antigos),
        "erros_exemplo": [r["erro"] for r in resultados if r.get("erro")][:10],
    }


def rodar_validacao(cliente: ClientePlataformaNova, escritorio_canonico: str | None = None,
                    tamanho: int = 1000, dias_recentes: int = 45) -> dict:
    """Roda a amostra contra a plataforma nova de verdade. Nao chamar em
    teste automatizado -- rede real, conta dedicada."""
    amostra = amostrar_processos(escritorio_canonico, tamanho, dias_recentes)
    resultados = []
    for item in amostra:
        numero_inpi = item["numero_inpi"]
        entrada = {"numero_inpi": numero_inpi, "recente": item["recente"],
                   "sucesso": False, "indexado": None, "erro": None}
        try:
            biblio = cliente.get_bibliographic_data(numero_inpi)
            entrada["sucesso"] = True
            entrada["indexado"] = bool(biblio)
        except PlataformaNovaError as exc:
            entrada["erro"] = str(exc)
        resultados.append(entrada)
        time.sleep(0.2)  # nao martelar a API numa rajada sem medir throughput antes
    return montar_relatorio(resultados)


def main() -> int:
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    login = os.environ["INPI_PAG_LOGIN"]
    senha = os.environ["INPI_PAG_PASSWORD"]
    cliente = ClientePlataformaNova(login, senha)
    relatorio = rodar_validacao(cliente)
    print(relatorio)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
