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

from inpi.coleta_ficha_extras import _coletados
from inpi.coleta_plataforma_nova import coletar_com_fallback_pepi
from inpi.mercado_fila import marcar, proximo_lote
from inpi.plataforma_nova import ClientePlataformaNova


def deve_parar(resumo: dict, tamanho_lote: int, limiar: float = 0.3) -> bool:
    """Proporcao de erro genuino (rede/servidor, ja nao inclui
    'nao encontrado' -- ver inpi.coleta_plataforma_nova._nao_encontrado)
    acima de `limiar` sinaliza bloqueio provavel. Lote vazio nunca para
    (evita divisao por zero e falso positivo)."""
    if tamanho_lote == 0:
        return False
    return (resumo.get("erros", 0) / tamanho_lote) > limiar
