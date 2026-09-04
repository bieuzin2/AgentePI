"""Loop continuo de enriquecimento de mercado: consome inpi/mercado_fila.py,
coleta via inpi/coleta_plataforma_nova.py::coletar_com_fallback_pepi com
escritorio_canonico=None e credencial PAG ISOLADA da producao
(INPI_PAG_LOGIN_MERCADO/INPI_PAG_PASSWORD_MERCADO -- nunca a de producao).

Sem tecnica de evasao de bloqueio: para limpo (nao insiste) quando a
proporcao de erro por lote sinaliza bloqueio -- ver deve_parar(). Retomada
e so a fila persistente: rodar de novo continua de onde parou.

CLI: `python -m inpi.coleta_mercado` roda o loop. Deliberadamente fora do
job semanal (vigilancia/executar.py nao importa este modulo).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

from inpi.coleta_ficha_extras import _coletados
from inpi.coleta_plataforma_nova import coletar_com_fallback_pepi
from inpi.mercado_fila import marcar, proximo_lote
from inpi.plataforma_nova import ClientePlataformaNova

# Task Scheduler nao herda o .env -- mesmo padrao de vigilancia/sync_motherduck.py.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def deve_parar(resumo: dict, tamanho_lote: int, limiar: float = 0.3) -> bool:
    """Proporcao de erro genuino (rede/servidor, ja nao inclui
    'nao encontrado' -- ver inpi.coleta_plataforma_nova._nao_encontrado)
    acima de `limiar` sinaliza bloqueio provavel. Lote vazio nunca para
    (evita divisao por zero e falso positivo)."""
    if tamanho_lote == 0:
        return False
    return (resumo.get("erros", 0) / tamanho_lote) > limiar


def processar_lote(cliente: ClientePlataformaNova, lote: list[str],
                   paralelismo: int = 8) -> dict:
    """Roda um lote via coletar_com_fallback_pepi (paralelismo real dentro
    do lote -- ver inpi.coleta_plataforma_nova.coletar_e_registrar) e marca
    a fila conforme o resultado. 'sucesso' = numero_inpi presente em
    _coletados() (cache em memoria de registrar(), atualizado nesta mesma
    chamada) apos rodar; o resto vira 'erro' -- nao fica 'pendente' pra
    sempre, senao a fila reprocessaria o mesmo item bloqueado a cada ciclo."""
    resumo = coletar_com_fallback_pepi(cliente, lote, escritorio_canonico=None,
                                       paralelismo=paralelismo)
    coletados_agora = _coletados()
    sucesso = [n for n in lote if n in coletados_agora]
    falha = [n for n in lote if n not in coletados_agora]
    marcar(sucesso, "coletado")
    marcar(falha, "erro")
    return resumo


def rodar_loop(tamanho_lote: int = 50, limiar_bloqueio: float = 0.3,
              paralelismo: int = 8, dormir_segundos_em_erro: int = 30) -> None:
    """Sem sleep fixo entre lotes saudaveis -- so pausa (`dormir_segundos_em_erro`)
    quando o lote anterior teve QUALQUER erro, como respiro antes de tentar
    de novo (nao e backoff pra evadir bloqueio: se a proporcao de erro
    passar do limiar, para de vez, nao insiste com sleep nenhum -- ver
    deve_parar()). Sem erro nenhum, emenda direto no proximo lote."""
    login = os.environ.get("INPI_PAG_LOGIN_MERCADO")
    senha = os.environ.get("INPI_PAG_PASSWORD_MERCADO")
    if not login or not senha:
        print("INPI_PAG_LOGIN_MERCADO/INPI_PAG_PASSWORD_MERCADO ausentes no "
              ".env -- crie uma credencial PAG separada da producao antes "
              "de rodar isto (nunca reusar INPI_PAG_LOGIN de producao aqui).",
              flush=True)
        return

    cliente = ClientePlataformaNova(login, senha)
    try:
        while True:
            lote = proximo_lote(tamanho_lote)
            if not lote:
                print("Fila vazia -- nada a coletar.", flush=True)
                return
            resumo = processar_lote(cliente, lote, paralelismo=paralelismo)
            print(f"Lote de {len(lote)}: {resumo}", flush=True)
            if deve_parar(resumo, len(lote), limiar_bloqueio):
                print(f"Proporcao de erro acima do limiar ({limiar_bloqueio:.0%}) "
                      "-- possivel bloqueio. Parando (sem retomar sozinho).",
                      flush=True)
                return
            if resumo.get("erros", 0) > 0:
                time.sleep(dormir_segundos_em_erro)
    finally:
        cliente.fechar()


if __name__ == "__main__":
    rodar_loop()
