# Incremento sem re-varrer, migração de fonte e benchmark de mercado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Disparar `inpi/coleta_plataforma_nova.py::coletar_com_fallback_pepi()` só sobre processos com sinal de mudança (despacho novo no dump semanal + watermark mensal de segurança), em vez da carteira inteira; expor uma tool nova de benchmark carteira-vs-mercado; atualizar a superfície Copilot M365.

**Architecture:** Novo módulo `vigilancia/incremento_plataforma_nova.py` calcula a lista de prioridade via `EXCEPT` linha-inteira sobre `despachos` (mesma técnica de `vigilancia/sync_motherduck.py::_diff_tabela`, reutilizando seu helper `_colunas`) contra a cópia `inpi_anterior.duckdb` que `vigilancia/reingestao.py` já preserva — roda ANTES de `sync_motherduck.sincronizar_incremental()` apagar essa cópia. `vigilancia/executar.py` chama esse módulo logo após a reingestão. Seção 3 adiciona uma tabela de referência estática (`ipc_campo_tecnologico`) carregada pelo mesmo padrão de `procuradores-sigilo.csv`/`estatistica-nacional.csv` em `inpi/ingest.py`, e uma tool nova `inpi_benchmark_mercado` espelhando `inpi_carteira`/`inpi_estatistica_nacional`.

**Tech Stack:** Python, DuckDB (SQL puro via `duckdb` client), pytest (fixtures `tmp_path`/`monkeypatch`, sem framework de mock além de `unittest.mock` já usado no repo).

## Global Constraints

- Nenhuma tool MCP chama rede externa — toda coleta da plataforma nova é batch, disparada pelo job semanal (spec Seção 2).
- Credenciais via env var `INPI_PAG_LOGIN`/`INPI_PAG_PASSWORD` (mesmo par que `inpi/validar_plataforma_nova.py` já usa) — nunca hardcoded.
- Qualquer falha de rede/credencial no passo novo devolve `{"pulado": True, ...}` sem levantar exceção e sem derrubar o resto de `vigilancia/executar.py` — mesma convenção de `sincronizar()` para `MOTHERDUCK_TOKEN` ausente.
- `escritorio_canonico` da coleta própria é o literal `"CLARKE MODET"` — mesmo valor já hardcoded em testes/exemplos do repo (`inpi/test_anuidades_pagas.py`), sem novo campo de config.
- Sem `CREATE INDEX` novo, sem abstração para "fonte de coleta única" — YAGNI, só existe uma fonte primária (plataforma nova) e um fallback (pePI), já implementados.

---

### Task 1: `numeros_despacho_novo()` — lista de prioridade da semana

**Files:**
- Create: `vigilancia/incremento_plataforma_nova.py`
- Test: `vigilancia/test_incremento_plataforma_nova.py`

**Interfaces:**
- Consumes: `vigilancia.sync_motherduck._colunas(con, tabela) -> list[str]` (já existe, `vigilancia/sync_motherduck.py:63`). `inpi.db.BANCO` (Path, `inpi/ingest.py:28`, reexportado por `inpi/db.py`).
- Produces: `numeros_despacho_novo() -> list[str]` — lista de `numero_inpi` distintos. Task 2 e Task 3 consomem esta função.

- [ ] **Step 1: Write the failing test**

```python
# vigilancia/test_incremento_plataforma_nova.py
"""Testes do modulo de priorizacao da coleta incremental (sem rede)."""

from __future__ import annotations

import duckdb

import vigilancia.incremento_plataforma_nova as inc


def test_numeros_despacho_novo_sem_banco_anterior_devolve_vazio(monkeypatch, tmp_path):
    monkeypatch.setattr(inc, "BANCO_ANTERIOR", tmp_path / "nao-existe.duckdb")
    monkeypatch.setattr(inc, "BANCO_INPI", tmp_path / "inpi.duckdb")
    assert inc.numeros_despacho_novo() == []


def test_numeros_despacho_novo_identifica_processo_com_despacho_novo(monkeypatch, tmp_path):
    antigo_path = tmp_path / "inpi_anterior.duckdb"
    novo_path = tmp_path / "inpi.duckdb"

    con_a = duckdb.connect(str(antigo_path))
    con_a.execute("CREATE TABLE despachos (numero_inpi VARCHAR, codigo_despacho VARCHAR, data_rpi VARCHAR)")
    con_a.execute("INSERT INTO despachos VALUES ('P1', '1.1', '2026-08-01')")
    con_a.close()

    con_n = duckdb.connect(str(novo_path))
    con_n.execute("CREATE TABLE despachos (numero_inpi VARCHAR, codigo_despacho VARCHAR, data_rpi VARCHAR)")
    # P1: mesmo despacho de antes (sem mudanca) + despacho novo -> conta como mudou.
    # P2: so existia antes, sumiu (nao deve aparecer -- so novidade importa aqui).
    # P3: despacho totalmente novo.
    con_n.execute("""
        INSERT INTO despachos VALUES
            ('P1', '1.1', '2026-08-01'),
            ('P1', '2.1', '2026-08-29'),
            ('P3', '1.1', '2026-08-29')
    """)
    con_n.close()

    monkeypatch.setattr(inc, "BANCO_ANTERIOR", antigo_path)
    monkeypatch.setattr(inc, "BANCO_INPI", novo_path)

    resultado = inc.numeros_despacho_novo()

    assert sorted(resultado) == ["P1", "P3"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vigilancia/test_incremento_plataforma_nova.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vigilancia.incremento_plataforma_nova'`

- [ ] **Step 3: Write minimal implementation**

```python
# vigilancia/incremento_plataforma_nova.py
"""Prioriza a coleta incremental da plataforma nova (inpi/coleta_plataforma_nova.py):
so processos com sinal de mudanca real, nao a carteira inteira.

Duas fontes de prioridade (spec:
docs/superpowers/specs/2026-09-04-inpi-incremento-e-migracao-design.md):
  - numeros_despacho_novo(): despacho novo no dump semanal -- sinal primario,
    calculado ANTES de vigilancia.sync_motherduck.sincronizar_incremental()
    apagar inpi_anterior.duckdb (a copia que vigilancia.reingestao ja deixa
    antes de recriar o banco).
  - numeros_watermark_vencido(): rede de seguranca mensal, cobre mudanca sem
    despacho correspondente (achado da validacao ao vivo 2026-09-04: despacho
    novo NAO correlaciona 100% com mudanca real na plataforma nova).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from inpi.db import BANCO as BANCO_INPI
from vigilancia.sync_motherduck import _colunas

# Path proprio, mesmo calculo que vigilancia/reingestao.py e
# vigilancia/sync_motherduck.py ja fazem cada um por conta -- os tres modulos
# ficam desacoplados de proposito (nenhum importa BANCO_ANTERIOR dos outros).
BANCO_ANTERIOR = BANCO_INPI.with_name("inpi_anterior.duckdb")

# Task Scheduler nao herda o .env -- mesmo padrao de vigilancia/sync_motherduck.py.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def numeros_despacho_novo() -> list[str]:
    """DISTINCT numero_inpi cujas linhas de despachos sao novas nesta rodada
    (EXCEPT linha inteira contra inpi_anterior.duckdb -- mesma tecnica de
    vigilancia.sync_motherduck._diff_tabela, so keyed por numero_inpi em vez
    de subir a linha inteira pro MotherDuck). Sem inpi_anterior.duckdb
    (primeira rodada, ou o sync ja consumiu e apagou), devolve [] -- sem base
    para diff, nao ha erro a levantar."""
    import duckdb

    if not BANCO_ANTERIOR.exists() or not BANCO_INPI.exists():
        return []
    con = duckdb.connect(str(BANCO_INPI))
    try:
        antigo = str(BANCO_ANTERIOR).replace("'", "''")
        con.execute(f"ATTACH '{antigo}' AS antigo (READ_ONLY)")
        cols = ", ".join(_colunas(con, "despachos"))
        linhas = con.execute(
            f"SELECT DISTINCT numero_inpi FROM ("
            f"SELECT {cols} FROM despachos EXCEPT SELECT {cols} FROM antigo.despachos"
            f")"
        ).fetchall()
        return [r[0] for r in linhas]
    finally:
        con.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vigilancia/test_incremento_plataforma_nova.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add vigilancia/incremento_plataforma_nova.py vigilancia/test_incremento_plataforma_nova.py
git commit -m "feat(inpi): numeros_despacho_novo() -- prioridade semanal da coleta incremental"
```

---

### Task 2: `numeros_watermark_vencido()` — rede de segurança mensal

**Files:**
- Modify: `vigilancia/incremento_plataforma_nova.py`
- Test: `vigilancia/test_incremento_plataforma_nova.py`

**Interfaces:**
- Consumes: nada novo (só `BANCO_INPI` já definido em Task 1). Tabelas `biblio`/`ficha_extras` (schema em `inpi/ingest.py:326-368`: `ficha_extras.coletado_em` é `VARCHAR` no formato `date.today().isoformat()`, ex. `"2026-09-04"`, gravado por `inpi/coleta_ficha_extras.py::registrar`).
- Produces: `numeros_watermark_vencido(dias: int = 60) -> list[str]`. Task 3 consome.

- [ ] **Step 1: Write the failing test**

```python
# adicionar em vigilancia/test_incremento_plataforma_nova.py

from datetime import date, timedelta


def test_numeros_watermark_vencido_sem_banco_devolve_vazio(monkeypatch, tmp_path):
    monkeypatch.setattr(inc, "BANCO_INPI", tmp_path / "nao-existe.duckdb")
    assert inc.numeros_watermark_vencido() == []


def test_numeros_watermark_vencido_pega_nunca_coletado_e_antigo(monkeypatch, tmp_path):
    banco = tmp_path / "inpi.duckdb"
    con = duckdb.connect(str(banco))
    con.execute("CREATE TABLE biblio (numero_inpi VARCHAR)")
    con.execute("INSERT INTO biblio VALUES ('P1'), ('P2'), ('P3')")
    con.execute("CREATE TABLE ficha_extras (numero_inpi VARCHAR, coletado_em VARCHAR)")
    recente = date.today().isoformat()
    antigo = (date.today() - timedelta(days=90)).isoformat()
    con.execute(
        "INSERT INTO ficha_extras VALUES (?, ?), (?, ?)",
        ["P1", recente, "P2", antigo],
    )
    # P3: nunca coletado (sem linha em ficha_extras) -- tambem deve entrar.
    con.close()

    monkeypatch.setattr(inc, "BANCO_INPI", banco)

    resultado = inc.numeros_watermark_vencido(dias=60)

    assert sorted(resultado) == ["P2", "P3"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vigilancia/test_incremento_plataforma_nova.py -k watermark -v`
Expected: FAIL — `AttributeError: module 'vigilancia.incremento_plataforma_nova' has no attribute 'numeros_watermark_vencido'`

- [ ] **Step 3: Write minimal implementation**

Append to `vigilancia/incremento_plataforma_nova.py`:

```python
def numeros_watermark_vencido(dias: int = 60) -> list[str]:
    """numero_inpi de biblio sem coleta da plataforma nova ha mais de `dias`,
    ou nunca coletados. Rede de seguranca mensal (spec: despacho novo nao
    correlaciona 100% com mudanca real -- ver docstring do modulo)."""
    import duckdb

    if not BANCO_INPI.exists():
        return []
    con = duckdb.connect(str(BANCO_INPI), read_only=True)
    try:
        linhas = con.execute(
            """SELECT b.numero_inpi FROM biblio b
               LEFT JOIN ficha_extras f USING (numero_inpi)
               WHERE f.numero_inpi IS NULL
                  OR try_strptime(f.coletado_em, '%Y-%m-%d') < current_date - INTERVAL (?) DAY""",
            [dias],
        ).fetchall()
        return [r[0] for r in linhas]
    finally:
        con.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vigilancia/test_incremento_plataforma_nova.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add vigilancia/incremento_plataforma_nova.py vigilancia/test_incremento_plataforma_nova.py
git commit -m "feat(inpi): numeros_watermark_vencido() -- rede de seguranca mensal"
```

---

### Task 3: `rodar_incremento()` + integração em `vigilancia/executar.py`

**Files:**
- Modify: `vigilancia/incremento_plataforma_nova.py`
- Modify: `vigilancia/executar.py:118-190` (função `executar()`)
- Test: `vigilancia/test_incremento_plataforma_nova.py`, `vigilancia/test_executar.py`

**Interfaces:**
- Consumes: `inpi.coleta_plataforma_nova.coletar_com_fallback_pepi(cliente, numeros_inpi, escritorio_canonico, fonte=FONTE_PADRAO, paralelismo=4) -> dict` (`inpi/coleta_plataforma_nova.py:102-127`). `inpi.plataforma_nova.ClientePlataformaNova(login: str, senha: str, http=None)` + `.fechar() -> None` (`inpi/plataforma_nova.py:42-115`). `numeros_despacho_novo()`/`numeros_watermark_vencido()` de Tasks 1-2. `executar.primeira_execucao_do_mes(ref) -> bool` (já existe, `vigilancia/executar.py:67-73`).
- Produces: `rodar_incremento(numeros_inpi: list[str], escritorio_canonico: str = "CLARKE MODET") -> dict`. `executar()` passa a devolver a chave `"incremento_plataforma_nova"` no dict de resultado.

- [ ] **Step 1: Write the failing test**

```python
# adicionar em vigilancia/test_incremento_plataforma_nova.py

def test_rodar_incremento_sem_numeros_pula(monkeypatch):
    assert inc.rodar_incremento([]) == {
        "pulado": True, "mensagem": "nenhum numero_inpi na lista de prioridade."
    }


def test_rodar_incremento_sem_credencial_pula(monkeypatch):
    monkeypatch.delenv("INPI_PAG_LOGIN", raising=False)
    monkeypatch.delenv("INPI_PAG_PASSWORD", raising=False)
    r = inc.rodar_incremento(["P1"])
    assert r == {"pulado": True, "mensagem": "INPI_PAG_LOGIN/INPI_PAG_PASSWORD ausentes."}


def test_rodar_incremento_chama_coletar_com_fallback_pepi(monkeypatch):
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("INPI_PAG_LOGIN", "user")
    monkeypatch.setenv("INPI_PAG_PASSWORD", "pass")
    cliente_mock = MagicMock()
    with patch("inpi.plataforma_nova.ClientePlataformaNova", return_value=cliente_mock) as Cliente, \
         patch("inpi.coleta_plataforma_nova.coletar_com_fallback_pepi",
               return_value={"registrados": 1}) as coletar:
        r = inc.rodar_incremento(["P1", "P2"], escritorio_canonico="CLARKE MODET")

    Cliente.assert_called_once_with("user", "pass")
    coletar.assert_called_once_with(cliente_mock, ["P1", "P2"], "CLARKE MODET")
    cliente_mock.fechar.assert_called_once()
    assert r == {"registrados": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vigilancia/test_incremento_plataforma_nova.py -k rodar_incremento -v`
Expected: FAIL — `AttributeError: module 'vigilancia.incremento_plataforma_nova' has no attribute 'rodar_incremento'`

- [ ] **Step 3: Write minimal implementation**

Append to `vigilancia/incremento_plataforma_nova.py`:

```python
def rodar_incremento(numeros_inpi: list[str],
                     escritorio_canonico: str = "CLARKE MODET") -> dict:
    """Roda coletar_com_fallback_pepi sobre `numeros_inpi` com um cliente
    autenticado novo. Login/senha vem de INPI_PAG_LOGIN/INPI_PAG_PASSWORD --
    mesma env var que inpi/validar_plataforma_nova.py usa. Sem numeros ou sem
    credencial, devolve {"pulado": True, ...} sem tentar rede -- mesma
    convencao de vigilancia.sync_motherduck.sincronizar() para
    MOTHERDUCK_TOKEN ausente."""
    if not numeros_inpi:
        return {"pulado": True, "mensagem": "nenhum numero_inpi na lista de prioridade."}
    login = os.environ.get("INPI_PAG_LOGIN")
    senha = os.environ.get("INPI_PAG_PASSWORD")
    if not login or not senha:
        return {"pulado": True, "mensagem": "INPI_PAG_LOGIN/INPI_PAG_PASSWORD ausentes."}

    from inpi.coleta_plataforma_nova import coletar_com_fallback_pepi
    from inpi.plataforma_nova import ClientePlataformaNova

    cliente = ClientePlataformaNova(login, senha)
    try:
        return coletar_com_fallback_pepi(cliente, numeros_inpi, escritorio_canonico)
    finally:
        cliente.fechar()
```

Modify `vigilancia/executar.py`:

```python
# no topo, junto aos outros imports do pacote:
from vigilancia import email_alerta, incremento_plataforma_nova, reingestao, vigias
```

```python
# dentro de executar(), logo apos o bloco de reingestao (linha ~128), ANTES de
# ler cfg["carteira"] -- tem de rodar enquanto inpi_anterior.duckdb ainda existe,
# ou seja, antes de sincronizar_incremental() (chamado mais abaixo) apagar a copia.
    prioridade = incremento_plataforma_nova.numeros_despacho_novo()
    if primeira_execucao_do_mes(ref):
        prioridade = sorted(set(prioridade) | set(
            incremento_plataforma_nova.numeros_watermark_vencido()))
    incremento = incremento_plataforma_nova.rodar_incremento(prioridade)
```

```python
# no dict devolvido por executar(), junto de "sync_motherduck":
    return {
        "executado_em": ref.isoformat(),
        "sync_motherduck": sync,
        "incremento_plataforma_nova": incremento,
        "desde": desde,
        ...
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest vigilancia/test_incremento_plataforma_nova.py vigilancia/test_executar.py -v`
Expected: PASS — todos os testes de `test_incremento_plataforma_nova.py`, e os dois testes existentes de `test_executar.py` continuam passando (sem `INPI_PAG_LOGIN` no ambiente de teste, `rodar_incremento` sempre cai em `pulado=True`, sem rede).

- [ ] **Step 5: Commit**

```bash
git add vigilancia/incremento_plataforma_nova.py vigilancia/executar.py vigilancia/test_incremento_plataforma_nova.py
git commit -m "feat(inpi): integra coleta incremental da plataforma nova ao ciclo semanal"
```

---

### Task 4: Tabela de referência `ipc_campo_tecnologico`

**Context:** `inpi_benchmark_mercado` (Task 5) precisa cruzar a carteira (código IPC, tabela `ipc.simbolo`) com `estatistica_nacional.campo_tecnologico` (taxonomia WIPO-35/Schmoch). Essa concordância IPC→campo-tecnológico é uma tabela pública e estática (não precisa raspar nada) — mas os valores em si (qual subclasse IPC cai em qual dos 35 campos) vêm de uma fonte externa oficial, não podem ser inventados aqui. **Este task inclui uma etapa manual de obtenção do dado antes de codar.**

**Files:**
- Create: `inpi/referencias/ipc-campo-tecnologico.csv`
- Modify: `inpi/ingest.py` (nova constante + nova função `_mescla_ipc_campo_tecnologico`, chamada em `main()`)
- Test: `inpi/test_ingest.py` (criar se não existir; ver Step 4 para checar)

**Interfaces:**
- Consumes: padrão já estabelecido em `inpi/ingest.py:284-323` (`_mescla_procuradores_sigilo`) e `:410-435` (`_mescla_estatistica_nacional`) — `read_csv(..., columns={...})` + `CREATE OR REPLACE TABLE`.
- Produces: tabela `ipc_campo_tecnologico(ipc_subclasse VARCHAR, campo_tecnologico VARCHAR)`. Task 5 consome via `JOIN ipc_campo_tecnologico ON substr(i.simbolo, 1, 4) = ipc_subclasse`.

- [ ] **Step 1: Obter a concordância IPC→WIPO-35 (manual, antes de codar)**

Baixe a tabela de concordância pública IPC-para-campo-tecnológico (classificação
Schmoch/WIPO-35, a mesma que o Portal de Estatísticas do INPI usa — ver
`docs/pesquisa/inpi_plataforma_nova.md` para contexto de por que o Portal usa
essa taxonomia). Fontes conhecidas: WIPO Statistics Database
(wipo.int/econ_stat) publica a "Table 1: Concordance IPC — 35 fields", e a
OECD (OECD Patent Database) republica a mesma tabela como CSV. Salve o
resultado em `inpi/referencias/ipc-campo-tecnologico.csv` com exatamente duas
colunas, cabeçalho incluído:

```csv
ipc_subclasse,campo_tecnologico
A61K,Farmacêutica
C07D,Química Orgânica Fina
...
```

`ipc_subclasse` é o prefixo de 4 caracteres (classe+subclasse, ex. `A61K`,
`C08L`) — mesmo nível que `inpi/mercado.py:423` já usa para filtrar
(`i.simbolo LIKE ?` com prefixo). `campo_tecnologico` deve usar exatamente os
mesmos rótulos de `estatistica_nacional.campo_tecnologico` (conferir com
`SELECT DISTINCT campo_tecnologico FROM estatistica_nacional` após a Fase 1
do spec anterior já ter carregado essa tabela) — sem isso o `JOIN` da Task 5
não bate nenhuma linha.

- [ ] **Step 2: Write the failing test**

```python
# inpi/test_ingest.py (criar se nao existir)
"""Testes dos mesclas de referencia estatica de inpi/ingest.py (sem rede,
sem baixar dump -- so a logica de merge do CSV de referencia)."""

from __future__ import annotations

import duckdb

from inpi import ingest


def test_mescla_ipc_campo_tecnologico(monkeypatch, tmp_path):
    csv = tmp_path / "ipc-campo-tecnologico.csv"
    csv.write_text(
        "ipc_subclasse,campo_tecnologico\nA61K,Farmacêutica\nC08L,Polímeros\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ingest, "IPC_CAMPO_TECNOLOGICO", csv)

    con = duckdb.connect()
    ingest._mescla_ipc_campo_tecnologico(con)

    linhas = con.execute(
        "SELECT ipc_subclasse, campo_tecnologico FROM ipc_campo_tecnologico ORDER BY 1"
    ).fetchall()
    assert linhas == [("A61K", "Farmacêutica"), ("C08L", "Polímeros")]


def test_mescla_ipc_campo_tecnologico_sem_csv_nao_cria_tabela(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest, "IPC_CAMPO_TECNOLOGICO", tmp_path / "nao-existe.csv")
    con = duckdb.connect()
    ingest._mescla_ipc_campo_tecnologico(con)
    tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert "ipc_campo_tecnologico" not in tabelas
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest inpi/test_ingest.py -v`
Expected: FAIL — `AttributeError: module 'inpi.ingest' has no attribute 'IPC_CAMPO_TECNOLOGICO'`

- [ ] **Step 4: Write minimal implementation**

Add near the other reference-path constants in `inpi/ingest.py` (after line 31):

```python
IPC_CAMPO_TECNOLOGICO = RAIZ / "referencias" / "ipc-campo-tecnologico.csv"
```

Add function (mirroring `_mescla_estatistica_nacional`, after it at line ~436):

```python
def _mescla_ipc_campo_tecnologico(con) -> None:
    """Carrega a concordancia publica e estatica IPC-subclasse -> campo
    tecnologico WIPO-35 (mesma taxonomia que estatistica_nacional.campo_tecnologico
    -- ver inpi/referencias/ipc-campo-tecnologico.csv). Dado publico, sem coleta
    -- se o CSV nao existir ainda, a tabela simplesmente nao e criada (mesma
    regra de tolerancia de _mescla_ficha_extras/_mescla_estatistica_nacional)."""
    if not IPC_CAMPO_TECNOLOGICO.exists():
        return
    t0 = time.time()
    caminho = IPC_CAMPO_TECNOLOGICO.as_posix()
    con.execute(f"""
      CREATE OR REPLACE TABLE ipc_campo_tecnologico AS
      SELECT DISTINCT * FROM read_csv('{caminho}', header=true, delim=',',
        quote='"', escape='"',
        columns={{'ipc_subclasse': 'VARCHAR', 'campo_tecnologico': 'VARCHAR'}})
    """)
    n = con.execute("SELECT count(*) FROM ipc_campo_tecnologico").fetchone()[0]
    print(f"  ipc_campo_tecnologico {n:>7,} linhas   {time.time() - t0:5.1f}s", flush=True)
```

Wire into `main()` (`inpi/ingest.py:482-487`, next to the other `_mescla_*` calls):

```python
    _mescla_procuradores_sigilo(con)
    _mescla_ficha_extras(con)
    _mescla_estatistica_nacional(con)
    _mescla_ipc_campo_tecnologico(con)
    _materializa_nomes(con)
    _materializa_titulares(con)
    _vota_identidade(con)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest inpi/test_ingest.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add inpi/referencias/ipc-campo-tecnologico.csv inpi/ingest.py inpi/test_ingest.py
git commit -m "feat(inpi): carrega concordancia IPC->campo tecnologico WIPO-35"
```

---

### Task 5: Tool `inpi_benchmark_mercado`

**Files:**
- Create: `inpi/benchmark_mercado.py`
- Modify: `inpi/inpi_mcp.py` (import de registro, mesmo padrão de `inpi_estatistica_nacional`)
- Test: `inpi/test_benchmark_mercado.py`

**Interfaces:**
- Consumes: `inpi.consulta._linhas(sql, params) -> list[dict]`, `inpi.consulta._tem_tabela(nome) -> bool` (já usados por `inpi/estatistica_nacional.py:12,48`). `inpi.mercado._chave_escritorio(escritorio) -> str` (`inpi/mercado.py:226`, resolve grafia pra chave canônica). `inpi.mcp_app.mcp` (decorator `@mcp.tool()`).
- Produces: `inpi_benchmark_mercado(escritorio: str, ano_inicial: int | None = None, ano_final: int | None = None, campo_tecnologico: str | None = None) -> dict`, registrada como tool MCP.

- [ ] **Step 1: Write the failing test**

```python
# inpi/test_benchmark_mercado.py
"""Testes de inpi_benchmark_mercado contra um banco DuckDB minimo em memoria."""

from __future__ import annotations

import duckdb
import pytest

import inpi.benchmark_mercado as bm


@pytest.fixture
def con(monkeypatch):
    c = duckdb.connect()
    c.execute("CREATE TABLE procuradores (numero_inpi VARCHAR, procurador VARCHAR)")
    c.execute("CREATE TABLE escritorios (original VARCHAR, chave VARCHAR)")
    c.execute("CREATE TABLE ipc (numero_inpi VARCHAR, simbolo VARCHAR)")
    c.execute("CREATE TABLE biblio (numero_inpi VARCHAR, data_deposito VARCHAR)")
    c.execute("CREATE TABLE ipc_campo_tecnologico (ipc_subclasse VARCHAR, campo_tecnologico VARCHAR)")
    c.execute("CREATE TABLE estatistica_nacional (ano INTEGER, campo_tecnologico VARCHAR, depositos INTEGER, concessoes INTEGER)")

    c.execute("INSERT INTO procuradores VALUES ('P1', 'CLARKE MODET'), ('P2', 'CLARKE MODET')")
    c.execute("INSERT INTO escritorios VALUES ('CLARKE MODET', 'CLARKE MODET')")
    c.execute("INSERT INTO ipc VALUES ('P1', 'A61K0031'), ('P2', 'A61K0009')")
    c.execute("INSERT INTO biblio VALUES ('P1', '2023-05-01'), ('P2', '2023-06-01')")
    c.execute("INSERT INTO ipc_campo_tecnologico VALUES ('A61K', 'Farmacêutica')")
    c.execute("INSERT INTO estatistica_nacional VALUES (2023, 'Farmacêutica', 1000, 400)")

    def _linhas(sql, params=()):
        cur = c.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    monkeypatch.setattr(bm, "_linhas", _linhas)
    monkeypatch.setattr(bm, "_tem_tabela", lambda nome: True)
    return c


def test_benchmark_mercado_compara_carteira_com_nacional(con):
    r = bm.inpi_benchmark_mercado("CLARKE MODET", ano_inicial=2023, ano_final=2023,
                                  campo_tecnologico="Farmacêutica")

    assert r["carteira"]["depositos"] == 2
    assert r["nacional"]["depositos"] == 1000
    assert r["share_mercado_pct"] == pytest.approx(0.2)


def test_benchmark_mercado_sem_estatistica_nacional_avisa(con, monkeypatch):
    monkeypatch.setattr(bm, "_tem_tabela", lambda nome: nome != "estatistica_nacional")
    r = bm.inpi_benchmark_mercado("CLARKE MODET")
    assert r["erro"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest inpi/test_benchmark_mercado.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'inpi.benchmark_mercado'`

- [ ] **Step 3: Write minimal implementation**

```python
# inpi/benchmark_mercado.py
"""Compara a carteira de um escritorio contra o volume nacional agregado
(estatistica_nacional, Portal de Estatisticas do INPI) por campo tecnologico.

Depende de ipc_campo_tecnologico (inpi/ingest.py::_mescla_ipc_campo_tecnologico)
para cruzar o codigo IPC da carteira com o campo_tecnologico da taxonomia
WIPO-35 que estatistica_nacional usa -- sem essa tabela, so da pra comparar
por ano/decisao (sem quebra por area tecnica)."""

from __future__ import annotations

from inpi.consulta import _linhas, _tem_tabela
from inpi.mcp_app import mcp
from inpi.mercado import _chave_escritorio


@mcp.tool()
def inpi_benchmark_mercado(
    escritorio: str, ano_inicial: int | None = None, ano_final: int | None = None,
    campo_tecnologico: str | None = None,
) -> dict:
    """Compara a carteira de um escritorio com o volume NACIONAL agregado
    (Portal de Estatisticas do INPI) no mesmo campo tecnologico/periodo --
    share de mercado e volume absoluto lado a lado.

    USE QUANDO: perguntarem "que fatia do mercado farmaceutico nacional a
    carteira representa", "como a carteira cresce comparado ao pais" -- ou
    seja, comparativo carteira-vs-mercado, nao so ranking entre escritorios
    (para isso, use inpi_mercado).

    Args:
        escritorio: grafia de escritorio (resolvida pela chave canonica, como
            em inpi_carteira).
        ano_inicial/ano_final: filtro de ano de deposito (inclusive).
        campo_tecnologico: taxonomia WIPO-35 (ex.: 'Farmacêutica'). Sem
            ipc_campo_tecnologico carregada, ignorado -- resultado sai sem
            quebra por campo.
    """
    if not _tem_tabela("estatistica_nacional"):
        return {"erro": True, "mensagem": (
            "Tabela estatistica_nacional ausente -- rode "
            "inpi/estatistica_publica.py e depois inpi/ingest.py.")}

    tem_ipc_campo = _tem_tabela("ipc_campo_tecnologico")
    if campo_tecnologico and not tem_ipc_campo:
        return {"erro": True, "mensagem": (
            "Tabela ipc_campo_tecnologico ausente -- sem ela nao da pra filtrar "
            "por campo_tecnologico. Rode inpi/ingest.py apos carregar "
            "inpi/referencias/ipc-campo-tecnologico.csv.")}

    chave = _chave_escritorio(escritorio)

    cond_carteira, params_carteira = ["e.chave = ?"], [chave]
    if ano_inicial:
        cond_carteira.append("substr(b.data_deposito, 1, 4)::INTEGER >= ?")
        params_carteira.append(ano_inicial)
    if ano_final:
        cond_carteira.append("substr(b.data_deposito, 1, 4)::INTEGER <= ?")
        params_carteira.append(ano_final)
    join_campo = ""
    if campo_tecnologico:
        join_campo = " JOIN ipc_campo_tecnologico ct ON substr(i.simbolo, 1, 4) = ct.ipc_subclasse"
        cond_carteira.append("ct.campo_tecnologico = ?")
        params_carteira.append(campo_tecnologico)

    carteira = _linhas(
        f"""SELECT count(DISTINCT p.numero_inpi) AS depositos
            FROM procuradores p
            JOIN escritorios e ON e.original = p.procurador
            LEFT JOIN ipc i USING (numero_inpi)
            LEFT JOIN biblio b USING (numero_inpi)
            {join_campo}
            WHERE {' AND '.join(cond_carteira)}""",
        params_carteira,
    )[0]

    cond_nac, params_nac = [], []
    if ano_inicial:
        cond_nac.append("ano >= ?")
        params_nac.append(ano_inicial)
    if ano_final:
        cond_nac.append("ano <= ?")
        params_nac.append(ano_final)
    if campo_tecnologico:
        cond_nac.append("campo_tecnologico = ?")
        params_nac.append(campo_tecnologico)
    where_nac = ("WHERE " + " AND ".join(cond_nac)) if cond_nac else ""

    nacional = _linhas(
        f"SELECT sum(depositos) AS depositos, sum(concessoes) AS concessoes "
        f"FROM estatistica_nacional {where_nac}",
        params_nac,
    )[0]

    dep_carteira = carteira["depositos"] or 0
    dep_nacional = nacional["depositos"] or 0
    share = round(dep_carteira / dep_nacional * 100, 4) if dep_nacional else None

    return {
        "escritorio": escritorio,
        "chave": chave,
        "filtro": {"ano_inicial": ano_inicial, "ano_final": ano_final,
                   "campo_tecnologico": campo_tecnologico},
        "carteira": {"depositos": dep_carteira},
        "nacional": {"depositos": dep_nacional, "concessoes": nacional["concessoes"] or 0},
        "share_mercado_pct": share,
        "fonte_nacional": "Portal de Estatisticas do INPI (servicos.estatistica.inpi.gov.br)",
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest inpi/test_benchmark_mercado.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Register the tool** (mirror `inpi/inpi_mcp.py:94` for `inpi_estatistica_nacional`)

Add to `inpi/inpi_mcp.py` near line 94:

```python
from inpi.benchmark_mercado import inpi_benchmark_mercado  # noqa: F401
```

- [ ] **Step 6: Run full inpi test suite**

Run: `python -m pytest inpi/ -q`
Expected: PASS, no regressions (new import side-effect only registers a tool, doesn't change existing behavior)

- [ ] **Step 7: Commit**

```bash
git add inpi/benchmark_mercado.py inpi/inpi_mcp.py inpi/test_benchmark_mercado.py
git commit -m "feat(inpi): tool inpi_benchmark_mercado -- carteira vs. mercado nacional"
```

---

### Task 6: Expor tools novas no servidor Copilot M365

**Files:**
- Modify: `remoto/servidor_mcp.py:100-150` (imports + `TOOLS`)
- Modify: `docs/agente-copilot.md:48-51` (lista "Caso B" do runbook)

**Interfaces:**
- Consumes: `inpi.estatistica_nacional.inpi_estatistica_nacional` (já existe, hoje só no servidor local — confirmado ausente de `TOOLS` em `remoto/servidor_mcp.py`). `inpi.benchmark_mercado.inpi_benchmark_mercado` (Task 5).
- Produces: nada consumido por outro task — é o fim da cadeia.

- [ ] **Step 1: Adicionar imports e entradas em `TOOLS`**

Em `remoto/servidor_mcp.py`, junto aos outros imports de `inpi/` (perto da linha 100-109):

```python
from inpi.estatistica_nacional import inpi_estatistica_nacional
from inpi.benchmark_mercado import inpi_benchmark_mercado
```

Em `TOOLS` (linha ~118-150), no grupo "inteligencia analitica" (linha 141-142):

```python
    # inteligencia analitica: motor de estatistica generico + stats de exigencias +
    # agregado nacional publico + benchmark carteira-vs-mercado
    inpi_estatistica, inpi_exigencias_stats,
    inpi_estatistica_nacional, inpi_benchmark_mercado,
```

- [ ] **Step 2: Rodar o teste existente do servidor remoto**

Run: `python -m pytest remoto/test_servidor_mcp.py -v`
Expected: PASS (o teste cobre `_chave_valida`, função pura — adicionar tools a `TOOLS` não quebra nada ali; se o teste também fizer `import servidor_mcp` para checar `montar_app()`, confirma que os dois `add_tool` novos não colidem por nome)

- [ ] **Step 3: Atualizar o runbook de refresh**

Em `docs/agente-copilot.md`, "Caso B" (linha 48-51), adicionar as duas tools à lista de exemplo de tools recém-adicionadas que precisam ser incluídas manualmente:

```
4. **Caso B — conectado tool a tool** (cada ação adicionada individualmente): adicione as
   novas manualmente pelo mesmo fluxo das antigas: `inpi_anuidades_pagas`,
   `inpi_peticoes_escritorio`, `inpi_reconciliar`, `fto_dominio_publico`,
   `inpi_gaps_protecao`, `inpi_responsavel_pi`, `inpi_estatistica_nacional`,
   `inpi_benchmark_mercado`.
```

- [ ] **Step 4: Commit**

```bash
git add remoto/servidor_mcp.py docs/agente-copilot.md
git commit -m "feat(inpi): expoe inpi_estatistica_nacional e inpi_benchmark_mercado no Copilot M365"
```

---

## Fora de escopo (herdado do spec, não repetido em tasks)

- Migração de fonte (Seção 2 do spec) — sem mudança de código: `ficha_peticoes` continua vindo só do pePI, `_COMPONENT_ID_EVENTOS` fica no código sem virar pipeline. Nenhum task necessário.
- Throughput/paralelismo maior da plataforma nova, investigação dos ~21% "não encontrado" no formato legado — pendências já registradas, fora desta implementação.
- Ajuste da heurística de prioridade (despacho-novo vs. watermark) com base em dados reais de produção — só dá para medir depois de 3-4 semanas rodando (ver "Verificação" do spec), não é um task de código.
