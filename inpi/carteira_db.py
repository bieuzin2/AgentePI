"""Conexao ao banco fisico carteira.duckdb -- neutro, sem esquema de negocio.

Este arquivo existe porque `tarefas.py` (tabela `tarefas`, lembretes) e
`radar.py` (tabela `radar_watermark`) vivem no mesmo arquivo fisico. Na Fase G
o antigo sistema de "carteira ingerida" (tabela `casos`, inpi/carteira.py) foi
removido -- nada mais depende de upload manual de portfolio -- mas o arquivo
fisico segue hospedando tarefas/radar. So a CONEXAO ficou aqui; cada tabela e
criada por quem a usa (tarefas.py::ESQUEMA, radar.py::ESQUEMA_RADAR).

MotherDuck (MOTHERDUCK_TOKEN no ambiente) tem prioridade sobre o arquivo
local -- AO CONTRARIO de inpi/db.py e enriquecimento/db.py, e de propósito:
tarefas/radar não têm dump local versionado, o MotherDuck é a ÚNICA fonte
compartilhada entre o agente remoto (Render/Teams) e qualquer uso local
(vigilancia/sync_motherduck.py recusa deliberadamente sincronizar `carteira`
justamente porque "o agente remoto cria tarefas direto na nuvem" -- não há
cópia local a preferir).

ARMADILHA PARA TESTES (não para produção): como qualquer import que carregue
o .env (inpi.familia_epo, entre outros) põe MOTHERDUCK_TOKEN no ambiente do
processo inteiro, testes que monkeypatcham `BANCO`/`BANCO_TAREFAS` para um
arquivo local temporário -- esperando isolamento -- acabam indo para o
MotherDuck de qualquer jeito se o token estiver no ambiente. Confirmado ao
vivo: rodar a suite local escreveu 72 linhas de lixo de teste na tabela
`tarefas` REAL do MotherDuck. O fix correto NÃO é mudar esta prioridade
(mudaria o comportamento de produção/uso interativo, que depende dela) -- é
o `conftest.py` da raiz, que limpa MOTHERDUCK_TOKEN do ambiente para todo
teste por padrão.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent

BANCO = RAIZ / "data" / "carteira.duckdb"


def conectar_carteira(banco: Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Conexao ao banco de carteira: MotherDuck (MOTHERDUCK_TOKEN) ou o arquivo
    local passado em 'banco'. Compartilhada por tarefas.py e radar.py.

    'banco' recebe o CAMINHO, nao um default fixo aqui: cada chamador passa a
    sua propria variavel BANCO/BANCO_TAREFAS de modulo, para que testes que
    monkeypatcham essa variavel continuem valendo mesmo com a conexao
    centralizada aqui."""
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if token:
        c = duckdb.connect(f"md:?motherduck_token={token}")
        c.execute("CREATE DATABASE IF NOT EXISTS carteira")
        c.execute("USE carteira")
        return c
    banco = banco if banco is not None else BANCO
    banco.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(banco), read_only=read_only)
