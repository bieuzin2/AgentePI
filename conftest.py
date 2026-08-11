"""Isolamento de testes contra bancos de producao no MotherDuck.

Qualquer import que carregue o .env (ex.: inpi.familia_epo, importado por
inpi.oposicoes -> inpi.inpi_mcp) poe MOTHERDUCK_TOKEN no ambiente do processo
pytest INTEIRO -- mesmo para testes que nunca pediram para falar com a nuvem.
Isso e inofensivo para inpi/db.py e enriquecimento/db.py (que preferem o
arquivo local quando ele existe -- e os dumps versionados sempre existem em
dev), mas e perigoso para inpi/carteira_db.py: ali o MotherDuck tem
prioridade DE PROPOSITO (nao ha copia local versionada de tarefas/radar, so a
base compartilhada com o agente remoto -- ver docstring do modulo). Testes de
inpi/test_tarefas.py e inpi/test_radar.py monkeypatcham BANCO/BANCO_TAREFAS
para um arquivo temporario esperando isolamento; sem este fixture, o token
vazado fazia esses testes escreverem direto na tabela `tarefas` REAL do
MotherDuck -- confirmado ao vivo, 72 linhas de lixo de teste apareceram lá
(a mesma base que o agente do Teams le em producao) e precisaram ser limpas
manualmente.

Testes que precisam simular "token presente" (inpi/test_db.py,
enriquecimento/test_db.py) chamam `monkeypatch.setenv(...)` dentro do proprio
corpo do teste -- como isso roda DEPOIS deste fixture autouse, no mesmo
`monkeypatch` da requisição, o setenv mais recente vence e esses testes
continuam funcionando normalmente.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _sem_motherduck_token_por_padrao(monkeypatch):
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
