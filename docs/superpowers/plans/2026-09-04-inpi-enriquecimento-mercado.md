# Enriquecimento de mercado (concorrentes → nacional) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coletar CPC/anuidades/petições (via `inpi/plataforma_nova.py`) pra
patentes fora da carteira própria — começando pelos concorrentes dos
clientes curados da Clarke Modet, expansível pra base nacional — sem tocar
o job semanal de produção e sem técnica de evasão de bloqueio.

**Architecture:** Fila persistente (`inpi/data/fila_mercado.duckdb`,
`mercado_fila.py`) populada por (1) concorrentes derivados via
`landscape.carteira_bridge.landscape_carteira()` (já existente, cruza CPC
da carteira do cliente com titulares mundiais via BigQuery) resolvidos pra
`numero_inpi` na base INPI local, e (2) opcionalmente o resto da base
nacional. Um processo novo e separado (`inpi/coleta_mercado.py`) consome a
fila em loop contínuo, reusando `coletar_com_fallback_pepi` já existente
com `escritorio_canonico=None` e credencial PAG isolada
(`INPI_PAG_LOGIN_MERCADO`), parando limpo se a proporção de erro por lote
sinalizar bloqueio.

**Tech Stack:** Python, DuckDB, `inpi/plataforma_nova.py` (cliente headless
já existente), `landscape/carteira_bridge.py` (BigQuery, ADC já
configurado — ver Global Constraints).

## Global Constraints

- Credencial PAG separada: `INPI_PAG_LOGIN_MERCADO`/`INPI_PAG_PASSWORD_MERCADO`
  no `.env` — **não existe ainda** (confirmado: só `INPI_PAG_LOGIN`/
  `INPI_PAG_PASSWORD` de produção estão no `.env` hoje). O código deve
  falhar com mensagem clara se ausente, nunca usar a credencial de produção
  como fallback silencioso. Criar essa credencial no INPI é passo manual do
  usuário, fora deste plano — só é bloqueante pra rodar de verdade, não pra
  codar/testar (testes usam cliente mockado).
- Nenhuma técnica de evasão de bloqueio (rotação de IP/Tor, múltiplas
  origens/CI, retomada automática contra bloqueio deliberado) — resiliência
  aqui é só retry/backoff em falha transitória de rede e checkpoint via
  fila persistente.
- `escritorio_canonico=None` pra tudo coletado por este sistema (nunca
  `"CLARKE MODET"`) — confirmado no spec que nenhuma tool filtra
  `WHERE escritorio_canonico = X` diretamente, só via JOIN
  `procuradores`/`escritorios`.
- Job semanal (`vigilancia/executar.py`) não é tocado por este plano —
  sistema deliberadamente separado, sem flag nova lá.
- Ritmo: lote de 50 `numero_inpi` por ciclo, 60s de espera entre ciclos
  (aproxima o throughput testado de ~45-50 fichas/min sem rajada maior que
  a já validada, ~700 processos — ver `docs/pesquisa/inpi_plataforma_nova.md`
  seção 6). Limiar de bloqueio: `erros / tamanho_lote > 0.3` → para o
  processo.
- BigQuery (landscape) requer ADC configurado
  (`gcloud auth application-default login`) — sem isso,
  `landscape_carteira`/`_rodar` já levantam `RuntimeError` com mensagem
  clara (comportamento existente, não precisa de guarda nova).

---

### Task 1: `inpi/mercado_fila.py` — fila persistente + derivação de concorrentes

**Files:**
- Create: `inpi/mercado_fila.py`
- Test: `inpi/test_mercado_fila.py`

**Interfaces:**
- Consumes: `landscape.carteira_bridge.landscape_carteira(cliente: str, top_cpc: int = 3, pais=None, desde=None, ate=None, confirmar_acima_10gb=False) -> dict` com chave `por_cpc: dict[str, {"top_titulares_mundiais": list[{"titular": str, "depositos": int}], ...}]` (`landscape/carteira_bridge.py:104-161`). `inpi.titulares.chaves_de(nome: str) -> list[dict]` com chave `chave` por linha, mais processada primeiro (`inpi/titulares.py:37-49`). `inpi.db.con() -> duckdb.DuckDBPyConnection` (read-only, singleton, `inpi/db.py:36`).
- Produces: `popular_concorrentes(top_cpc: int = 3, limite_titulares_por_cpc: int = 10) -> dict`, `popular_nacional(desde: str = "2020-01-01") -> dict`, `proximo_lote(n: int) -> list[str]`, `marcar(numeros_inpi: list[str], status: str) -> None`. Task 3 consome `proximo_lote`/`marcar`.

- [ ] **Step 1: Write the failing test — schema e `marcar`/`proximo_lote`**

```python
# inpi/test_mercado_fila.py
"""Testes de inpi/mercado_fila.py contra um arquivo DuckDB proprio em
tmp_path -- sem rede, sem tocar inpi.duckdb nem fila_mercado.duckdb real."""

from __future__ import annotations

import duckdb

import inpi.mercado_fila as fila


def test_proximo_lote_prioriza_concorrente_antes_de_nacional(monkeypatch, tmp_path):
    banco = tmp_path / "fila_mercado.duckdb"
    monkeypatch.setattr(fila, "BANCO_FILA", banco)

    con = fila._con()
    con.execute(
        "INSERT INTO fila_mercado VALUES "
        "('N1', 'nacional', 'pendente', 0, '2026-09-01'), "
        "('C1', 'concorrente', 'pendente', 0, '2026-09-01'), "
        "('C2', 'concorrente', 'pendente', 0, '2026-09-01')"
    )
    con.close()

    lote = fila.proximo_lote(2)

    assert lote == ["C1", "C2"]


def test_marcar_atualiza_status(monkeypatch, tmp_path):
    banco = tmp_path / "fila_mercado.duckdb"
    monkeypatch.setattr(fila, "BANCO_FILA", banco)

    con = fila._con()
    con.execute(
        "INSERT INTO fila_mercado VALUES "
        "('N1', 'nacional', 'pendente', 0, '2026-09-01')"
    )
    con.close()

    fila.marcar(["N1"], "coletado")

    con = fila._con()
    status = con.execute(
        "SELECT status FROM fila_mercado WHERE numero_inpi = 'N1'"
    ).fetchone()[0]
    con.close()
    assert status == "coletado"


def test_proximo_lote_ignora_ja_coletados(monkeypatch, tmp_path):
    banco = tmp_path / "fila_mercado.duckdb"
    monkeypatch.setattr(fila, "BANCO_FILA", banco)

    con = fila._con()
    con.execute(
        "INSERT INTO fila_mercado VALUES "
        "('N1', 'nacional', 'coletado', 1, '2026-09-01'), "
        "('N2', 'nacional', 'pendente', 0, '2026-09-01')"
    )
    con.close()

    assert fila.proximo_lote(10) == ["N2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest inpi/test_mercado_fila.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'inpi.mercado_fila'`

- [ ] **Step 3: Write minimal implementation — schema, `_con`, `proximo_lote`, `marcar`**

```python
# inpi/mercado_fila.py
"""Fila persistente de enriquecimento de mercado -- CPC/anuidades/peticoes
fora da carteira propria da Clarke Modet, via inpi/plataforma_nova.py.
Arquivo proprio (fila_mercado.duckdb), separado de inpi.duckdb: zero risco
de lock/concorrencia com o job semanal (vigilancia/executar.py).

Duas origens: 'concorrente' (derivado de landscape_carteira sobre os
clientes curados, ver popular_concorrentes) e 'nacional' (resto da base,
so entra quando o usuario decidir expandir, ver popular_nacional).
proximo_lote() sempre prioriza concorrente antes de nacional.

Ver docs/superpowers/specs/2026-09-04-inpi-enriquecimento-mercado-design.md.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent
BANCO_FILA = RAIZ / "data" / "fila_mercado.duckdb"


def _con() -> duckdb.DuckDBPyConnection:
    BANCO_FILA.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(BANCO_FILA))
    con.execute("""
        CREATE TABLE IF NOT EXISTS fila_mercado (
            numero_inpi VARCHAR,
            origem VARCHAR,
            status VARCHAR,
            tentativas INTEGER,
            atualizado_em VARCHAR
        )
    """)
    return con


def proximo_lote(n: int) -> list[str]:
    """Ate `n` numero_inpi pendentes, concorrente antes de nacional."""
    con = _con()
    try:
        linhas = con.execute(
            """SELECT numero_inpi FROM fila_mercado
               WHERE status = 'pendente'
               ORDER BY CASE origem WHEN 'concorrente' THEN 0 ELSE 1 END,
                        numero_inpi
               LIMIT ?""",
            [n],
        ).fetchall()
        return [r[0] for r in linhas]
    finally:
        con.close()


def marcar(numeros_inpi: list[str], status: str) -> None:
    """Atualiza status em lote (ex.: apos uma rodada de coleta)."""
    if not numeros_inpi:
        return
    con = _con()
    try:
        agora = date.today().isoformat()
        placeholders = ", ".join("?" * len(numeros_inpi))
        con.execute(
            f"""UPDATE fila_mercado
                SET status = ?, atualizado_em = ?,
                    tentativas = tentativas + 1
                WHERE numero_inpi IN ({placeholders})""",
            [status, agora, *numeros_inpi],
        )
    finally:
        con.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest inpi/test_mercado_fila.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add inpi/mercado_fila.py inpi/test_mercado_fila.py
git commit -m "feat(inpi): fila persistente de enriquecimento de mercado (schema + lote)"
```

- [ ] **Step 6: Write the failing test — `popular_nacional`**

```python
# adicionar em inpi/test_mercado_fila.py

def test_popular_nacional_insere_apenas_depositos_recentes_e_novos(monkeypatch, tmp_path):
    banco_fila = tmp_path / "fila_mercado.duckdb"
    monkeypatch.setattr(fila, "BANCO_FILA", banco_fila)

    banco_inpi = tmp_path / "inpi.duckdb"
    con_inpi = duckdb.connect(str(banco_inpi))
    con_inpi.execute("CREATE TABLE biblio (numero_inpi VARCHAR, data_deposito DATE)")
    con_inpi.execute(
        "INSERT INTO biblio VALUES "
        "('P1', DATE '2021-01-01'), "  # recente, deve entrar
        "('P2', DATE '2015-01-01')"    # antigo, nao deve entrar
    )
    con_inpi.close()
    monkeypatch.setattr(fila, "_con_inpi",
                        lambda: duckdb.connect(str(banco_inpi), read_only=True))

    # P1 ja esta na fila (de popular_concorrentes, por ex.) -- nao duplica.
    con = fila._con()
    con.execute(
        "INSERT INTO fila_mercado VALUES "
        "('P1', 'concorrente', 'pendente', 0, '2026-09-01')"
    )
    con.close()

    resultado = fila.popular_nacional(desde="2020-01-01")

    con = fila._con()
    linhas = con.execute(
        "SELECT numero_inpi, origem FROM fila_mercado ORDER BY numero_inpi"
    ).fetchall()
    con.close()

    assert resultado == {"inseridos": 1}
    assert linhas == [("P1", "concorrente")]  # P1 nao duplicou como 'nacional'
```

- [ ] **Step 7: Run test to verify it fails**

Run: `python -m pytest inpi/test_mercado_fila.py -k popular_nacional -v`
Expected: FAIL — `AttributeError: module 'inpi.mercado_fila' has no attribute 'popular_nacional'`

- [ ] **Step 8: Write minimal implementation — `popular_nacional`**

Append to `inpi/mercado_fila.py`:

```python
def _con_inpi() -> duckdb.DuckDBPyConnection:
    from inpi.db import BANCO as BANCO_INPI
    return duckdb.connect(str(BANCO_INPI), read_only=True)


def popular_nacional(desde: str = "2020-01-01") -> dict:
    """Insere na fila (origem='nacional') todo numero_inpi de biblio com
    deposito >= `desde` que ainda nao esta na fila (de qualquer origem) --
    so roda quando o usuario decidir expandir alem dos concorrentes."""
    con_inpi = _con_inpi()
    try:
        numeros = [r[0] for r in con_inpi.execute(
            "SELECT numero_inpi FROM biblio WHERE data_deposito >= ?", [desde]
        ).fetchall()]
    finally:
        con_inpi.close()

    con = _con()
    try:
        existentes = {r[0] for r in con.execute(
            "SELECT numero_inpi FROM fila_mercado"
        ).fetchall()}
        novos = [n for n in numeros if n not in existentes]
        agora = date.today().isoformat()
        con.executemany(
            "INSERT INTO fila_mercado VALUES (?, 'nacional', 'pendente', 0, ?)",
            [(n, agora) for n in novos],
        )
        return {"inseridos": len(novos)}
    finally:
        con.close()
```

- [ ] **Step 9: Run test to verify it passes**

Run: `python -m pytest inpi/test_mercado_fila.py -v`
Expected: PASS (4 tests)

- [ ] **Step 10: Commit**

```bash
git add inpi/mercado_fila.py inpi/test_mercado_fila.py
git commit -m "feat(inpi): popular_nacional() -- expande fila para toda a base recente"
```

- [ ] **Step 11: Write the failing test — `popular_concorrentes`**

```python
# adicionar em inpi/test_mercado_fila.py

from unittest.mock import patch


def test_popular_concorrentes_resolve_titulares_e_insere_numeros(monkeypatch, tmp_path):
    banco_fila = tmp_path / "fila_mercado.duckdb"
    monkeypatch.setattr(fila, "BANCO_FILA", banco_fila)

    clientes_csv = tmp_path / "clientes-clarke.csv"
    clientes_csv.write_text(
        "chave_canonica,nome_exibicao,processos,grafias\n"
        "HUAWEI TECHNOLOGIES,\"HUAWEI TECHNOLOGIES CO., LTD.\",2157,16\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(fila, "CLIENTES_CURADOS", clientes_csv)

    landscape_resultado = {
        "por_cpc": {
            "H01L": {
                "top_titulares_mundiais": [
                    {"titular": "SAMSUNG ELECTRONICS", "depositos": 500},
                ],
            },
        },
    }

    def _fake_chaves_de(nome):
        assert nome == "SAMSUNG ELECTRONICS"
        return [{"chave": "SAMSUNG ELECTRONICS CO LTD", "processos": 10,
                 "exemplo": "Samsung Electronics Co., Ltd."}]

    def _fake_numeros_do_titular(con, chave):
        assert chave == "SAMSUNG ELECTRONICS CO LTD"
        return ["S1", "S2"]

    with patch("inpi.mercado_fila.landscape_carteira",
               return_value=landscape_resultado) as mock_landscape, \
         patch("inpi.mercado_fila.chaves_de", side_effect=_fake_chaves_de), \
         patch("inpi.mercado_fila._numeros_do_titular",
               side_effect=_fake_numeros_do_titular):
        resultado = fila.popular_concorrentes(top_cpc=3, limite_titulares_por_cpc=10)

    mock_landscape.assert_called_once_with(
        cliente="HUAWEI TECHNOLOGIES CO., LTD.", top_cpc=3)

    con = fila._con()
    linhas = sorted(r[0] for r in con.execute(
        "SELECT numero_inpi FROM fila_mercado"
    ).fetchall())
    con.close()

    assert linhas == ["S1", "S2"]
    assert resultado == {"inseridos": 2, "titulares_resolvidos": 1,
                         "titulares_nao_resolvidos": []}


def test_popular_concorrentes_sem_csv_de_clientes_nao_faz_nada(monkeypatch, tmp_path):
    monkeypatch.setattr(fila, "BANCO_FILA", tmp_path / "fila_mercado.duckdb")
    monkeypatch.setattr(fila, "CLIENTES_CURADOS", tmp_path / "nao-existe.csv")

    resultado = fila.popular_concorrentes()

    assert resultado == {"inseridos": 0, "titulares_resolvidos": 0,
                         "titulares_nao_resolvidos": []}
```

- [ ] **Step 12: Run test to verify it fails**

Run: `python -m pytest inpi/test_mercado_fila.py -k popular_concorrentes -v`
Expected: FAIL — `AttributeError: module 'inpi.mercado_fila' has no attribute 'popular_concorrentes'`

- [ ] **Step 13: Write minimal implementation — `popular_concorrentes`**

Append to `inpi/mercado_fila.py`:

```python
import csv as _csv

CLIENTES_CURADOS = RAIZ / "referencias" / "clientes-clarke.csv"


def _numeros_do_titular(con: duckdb.DuckDBPyConnection, chave: str) -> list[str]:
    """numero_inpi distintos cujo titular casa a chave canonica -- mesma
    tabela `titulares` que inpi.titulares.chaves_de ja usa pra resolver."""
    return [r[0] for r in con.execute(
        """SELECT DISTINCT dp.numero_inpi FROM depositantes dp
           JOIN titulares t ON t.original = dp.depositante
           WHERE t.chave = ?""",
        [chave],
    ).fetchall()]


def popular_concorrentes(top_cpc: int = 3,
                         limite_titulares_por_cpc: int = 10) -> dict:
    """Deriva concorrentes via landscape_carteira() sobre os clientes
    curados da Clarke Modet (inpi/referencias/clientes-clarke.csv): para
    cada cliente, pega os titulares que mais depositam nas mesmas
    tecnologias (CPC) dele no mundo todo (BigQuery), resolve cada nome pra
    chave canonica na base INPI (inpi.titulares.chaves_de), e insere o
    portfolio BR desses titulares na fila com origem='concorrente'.

    Requer ADC do BigQuery configurado -- sem isso landscape_carteira ja
    levanta RuntimeError com instrucao clara (comportamento existente)."""
    if not CLIENTES_CURADOS.exists():
        return {"inseridos": 0, "titulares_resolvidos": 0,
                "titulares_nao_resolvidos": []}

    with CLIENTES_CURADOS.open(encoding="utf-8") as fh:
        clientes = [r["nome_exibicao"] for r in _csv.DictReader(fh)]

    con_inpi = _con_inpi()
    numeros_novos: set[str] = set()
    resolvidos = 0
    nao_resolvidos: list[str] = []
    try:
        for cliente_nome in clientes:
            resultado = landscape_carteira(cliente=cliente_nome, top_cpc=top_cpc)
            for info in resultado.get("por_cpc", {}).values():
                for linha in info.get("top_titulares_mundiais", [])[:limite_titulares_por_cpc]:
                    nome_titular = linha.get("titular")
                    if not nome_titular:
                        continue
                    candidatos = chaves_de(nome_titular)
                    if not candidatos:
                        nao_resolvidos.append(nome_titular)
                        continue
                    resolvidos += 1
                    chave = candidatos[0]["chave"]
                    numeros_novos.update(_numeros_do_titular(con_inpi, chave))
    finally:
        con_inpi.close()

    con = _con()
    try:
        existentes = {r[0] for r in con.execute(
            "SELECT numero_inpi FROM fila_mercado"
        ).fetchall()}
        novos = numeros_novos - existentes
        agora = date.today().isoformat()
        con.executemany(
            "INSERT INTO fila_mercado VALUES (?, 'concorrente', 'pendente', 0, ?)",
            [(n, agora) for n in novos],
        )
        return {"inseridos": len(novos), "titulares_resolvidos": resolvidos,
                "titulares_nao_resolvidos": nao_resolvidos}
    finally:
        con.close()
```

Add near the top of `inpi/mercado_fila.py` (with the other imports):

```python
from inpi.titulares import chaves_de
from landscape.carteira_bridge import landscape_carteira
```

- [ ] **Step 14: Run test to verify it passes**

Run: `python -m pytest inpi/test_mercado_fila.py -v`
Expected: PASS (6 tests)

- [ ] **Step 15: Commit**

```bash
git add inpi/mercado_fila.py inpi/test_mercado_fila.py
git commit -m "feat(inpi): popular_concorrentes() -- deriva concorrentes via landscape_carteira"
```

---

### Task 2: `coletar_e_registrar` — erro de rede genérico não derruba o lote

**Files:**
- Modify: `inpi/coleta_plataforma_nova.py:70-97`
- Test: `inpi/test_coleta_plataforma_nova.py`

**Interfaces:**
- Consumes: nada novo.
- Produces: mesmo comportamento de `coletar_e_registrar`, só o `except` ampliado. Task 3 depende disto pra não ter o loop de mercado morto por um timeout de rede.

- [ ] **Step 1: Write the failing test**

```python
# adicionar em inpi/test_coleta_plataforma_nova.py (ver imports existentes do arquivo)

import httpx


def test_erro_de_rede_generico_conta_como_erro_nao_propaga(monkeypatch):
    from unittest.mock import MagicMock
    import inpi.coleta_plataforma_nova as mod

    cliente = MagicMock()
    cliente.get_bibliographic_data.side_effect = [
        httpx.ConnectError("conexao recusada"),  # P1: erro de rede cru
        [{"inid": "52", "value": "A61K"}],        # P2: sucesso
    ]
    cliente.get_listing_data.return_value = {"objects": []}

    monkeypatch.setattr(mod, "registrar", lambda *a, **k: True)

    resumo = mod.coletar_e_registrar(cliente, ["P1", "P2"], escritorio_canonico=None)

    assert resumo["erros"] == 1
    assert resumo["registrados"] == 1
    assert resumo["nao_encontrados"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest inpi/test_coleta_plataforma_nova.py -k rede_generico -v`
Expected: FAIL — `httpx.ConnectError` propaga da chamada (não vira `resumo["erros"]`), o teste levanta a exceção em vez de comparar o dict.

- [ ] **Step 3: Write minimal implementation**

Em `inpi/coleta_plataforma_nova.py`, mudar o import e o `except` de
`coletar_e_registrar`:

```python
import httpx  # adicionar ao topo do arquivo, junto dos outros imports
```

```python
        except (PlataformaNovaError, httpx.HTTPError) as exc:
            if isinstance(exc, PlataformaNovaError) and _nao_encontrado(exc):
                resumo["nao_encontrados"].append(numero_inpi)
            else:
                resumo["erros"] += 1
```

(substitui o bloco `except PlataformaNovaError as exc:` existente em
`coletar_e_registrar`, linhas ~92-96)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest inpi/test_coleta_plataforma_nova.py -v`
Expected: PASS, incluindo todos os testes já existentes no arquivo (sem regressão)

- [ ] **Step 5: Commit**

```bash
git add inpi/coleta_plataforma_nova.py inpi/test_coleta_plataforma_nova.py
git commit -m "fix(inpi): erro de rede generico em coletar_e_registrar nao derruba o lote"
```

---

### Task 3: `inpi/coleta_mercado.py` — loop contínuo com detecção de bloqueio

**Files:**
- Create: `inpi/coleta_mercado.py`
- Test: `inpi/test_coleta_mercado.py`

**Interfaces:**
- Consumes: `inpi.mercado_fila.proximo_lote(n) -> list[str]`, `inpi.mercado_fila.marcar(numeros, status) -> None` (Task 1). `inpi.coleta_plataforma_nova.coletar_com_fallback_pepi(cliente, numeros_inpi, escritorio_canonico, fonte=FONTE_PADRAO, paralelismo=4, atualizar=False) -> dict` com chave `erros: int` (Task 2 garante que erro de rede cru também conta aqui). `inpi.coleta_ficha_extras._coletados() -> set[str]` (cache em memória de `numero_inpi` já gravados no processo atual, `inpi/coleta_ficha_extras.py:176-186`). `inpi.plataforma_nova.ClientePlataformaNova(login, senha)` com `.fechar()`.
- Produces: `deve_parar(resumo: dict, tamanho_lote: int, limiar: float = 0.3) -> bool`, `processar_lote(cliente, lote: list[str]) -> dict` (roda um lote, marca fila, devolve o resumo de `coletar_com_fallback_pepi`), `rodar_loop(tamanho_lote=50, limiar_bloqueio=0.3, dormir_segundos=60) -> None`. Nada consome isto depois — fim da cadeia.

- [ ] **Step 1: Write the failing test — `deve_parar`**

```python
# inpi/test_coleta_mercado.py
"""Testes de inpi/coleta_mercado.py com cliente/fila mockados -- sem rede."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import inpi.coleta_mercado as mod


def test_deve_parar_acima_do_limiar():
    resumo = {"erros": 16}
    assert mod.deve_parar(resumo, tamanho_lote=50, limiar=0.3) is True


def test_deve_parar_abaixo_do_limiar():
    resumo = {"erros": 5}
    assert mod.deve_parar(resumo, tamanho_lote=50, limiar=0.3) is False


def test_deve_parar_lote_vazio_nunca_para():
    assert mod.deve_parar({"erros": 0}, tamanho_lote=0, limiar=0.3) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest inpi/test_coleta_mercado.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'inpi.coleta_mercado'`

- [ ] **Step 3: Write minimal implementation — `deve_parar`**

```python
# inpi/coleta_mercado.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest inpi/test_coleta_mercado.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add inpi/coleta_mercado.py inpi/test_coleta_mercado.py
git commit -m "feat(inpi): coleta_mercado.deve_parar() -- deteccao de bloqueio por proporcao de erro"
```

- [ ] **Step 6: Write the failing test — `processar_lote`**

```python
# adicionar em inpi/test_coleta_mercado.py

def test_processar_lote_marca_sucesso_e_erro_na_fila():
    cliente = MagicMock()
    with patch("inpi.coleta_mercado.coletar_com_fallback_pepi",
               return_value={"registrados": 1, "erros": 1}) as mock_coletar, \
         patch("inpi.coleta_mercado._coletados", return_value={"P1"}), \
         patch("inpi.coleta_mercado.marcar") as mock_marcar:
        resumo = mod.processar_lote(cliente, ["P1", "P2"])

    mock_coletar.assert_called_once_with(cliente, ["P1", "P2"], escritorio_canonico=None)
    mock_marcar.assert_any_call(["P1"], "coletado")
    mock_marcar.assert_any_call(["P2"], "erro")
    assert resumo == {"registrados": 1, "erros": 1}
```

- [ ] **Step 7: Run test to verify it fails**

Run: `python -m pytest inpi/test_coleta_mercado.py -k processar_lote -v`
Expected: FAIL — `AttributeError: module 'inpi.coleta_mercado' has no attribute 'processar_lote'`

- [ ] **Step 8: Write minimal implementation — `processar_lote`**

Append to `inpi/coleta_mercado.py`:

```python
def processar_lote(cliente: ClientePlataformaNova, lote: list[str]) -> dict:
    """Roda um lote via coletar_com_fallback_pepi e marca a fila conforme o
    resultado. 'sucesso' = numero_inpi presente em _coletados() (cache em
    memoria de registrar(), atualizado nesta mesma chamada) apos rodar;
    o resto vira 'erro' -- nao fica 'pendente' pra sempre, senao a fila
    reprocessaria o mesmo item bloqueado a cada ciclo."""
    resumo = coletar_com_fallback_pepi(cliente, lote, escritorio_canonico=None)
    coletados_agora = _coletados()
    sucesso = [n for n in lote if n in coletados_agora]
    falha = [n for n in lote if n not in coletados_agora]
    marcar(sucesso, "coletado")
    marcar(falha, "erro")
    return resumo
```

- [ ] **Step 9: Run test to verify it passes**

Run: `python -m pytest inpi/test_coleta_mercado.py -v`
Expected: PASS (4 tests)

- [ ] **Step 10: Commit**

```bash
git add inpi/coleta_mercado.py inpi/test_coleta_mercado.py
git commit -m "feat(inpi): coleta_mercado.processar_lote() -- roda e marca fila por resultado"
```

- [ ] **Step 11: Write the failing test — `rodar_loop`**

```python
# adicionar em inpi/test_coleta_mercado.py

def test_rodar_loop_sem_credencial_nao_tenta_rede(monkeypatch, capsys):
    monkeypatch.delenv("INPI_PAG_LOGIN_MERCADO", raising=False)
    monkeypatch.delenv("INPI_PAG_PASSWORD_MERCADO", raising=False)

    with patch("inpi.coleta_mercado.ClientePlataformaNova") as mock_cliente:
        mod.rodar_loop()

    mock_cliente.assert_not_called()
    assert "INPI_PAG_LOGIN_MERCADO" in capsys.readouterr().out


def test_rodar_loop_para_quando_fila_vazia(monkeypatch, capsys):
    monkeypatch.setenv("INPI_PAG_LOGIN_MERCADO", "user")
    monkeypatch.setenv("INPI_PAG_PASSWORD_MERCADO", "pass")

    with patch("inpi.coleta_mercado.ClientePlataformaNova") as Cliente, \
         patch("inpi.coleta_mercado.proximo_lote", return_value=[]):
        mod.rodar_loop()

    Cliente.return_value.fechar.assert_called_once()
    assert "vazia" in capsys.readouterr().out.lower()


def test_rodar_loop_para_em_bloqueio_sem_dormir(monkeypatch):
    monkeypatch.setenv("INPI_PAG_LOGIN_MERCADO", "user")
    monkeypatch.setenv("INPI_PAG_PASSWORD_MERCADO", "pass")

    with patch("inpi.coleta_mercado.ClientePlataformaNova") as Cliente, \
         patch("inpi.coleta_mercado.proximo_lote", return_value=["P1"]), \
         patch("inpi.coleta_mercado.processar_lote",
               return_value={"erros": 1}), \
         patch("inpi.coleta_mercado.time.sleep") as mock_sleep:
        mod.rodar_loop(tamanho_lote=1, limiar_bloqueio=0.3)

    mock_sleep.assert_not_called()
    Cliente.return_value.fechar.assert_called_once()
```

- [ ] **Step 12: Run test to verify it fails**

Run: `python -m pytest inpi/test_coleta_mercado.py -k rodar_loop -v`
Expected: FAIL — `AttributeError: module 'inpi.coleta_mercado' has no attribute 'rodar_loop'`

- [ ] **Step 13: Write minimal implementation — `rodar_loop` + CLI**

Append to `inpi/coleta_mercado.py`:

```python
def rodar_loop(tamanho_lote: int = 50, limiar_bloqueio: float = 0.3,
              dormir_segundos: int = 60) -> None:
    login = os.environ.get("INPI_PAG_LOGIN_MERCADO")
    senha = os.environ.get("INPI_PAG_PASSWORD_MERCADO")
    if not login or not senha:
        print("INPI_PAG_LOGIN_MERCADO/INPI_PAG_PASSWORD_MERCADO ausentes no "
              ".env -- crie uma credencial PAG separada da producao antes "
              "de rodar isto (nunca reusar INPI_PAG_LOGIN de producao aqui).")
        return

    cliente = ClientePlataformaNova(login, senha)
    try:
        while True:
            lote = proximo_lote(tamanho_lote)
            if not lote:
                print("Fila vazia -- nada a coletar.")
                return
            resumo = processar_lote(cliente, lote)
            print(f"Lote de {len(lote)}: {resumo}")
            if deve_parar(resumo, len(lote), limiar_bloqueio):
                print(f"Proporcao de erro acima do limiar ({limiar_bloqueio:.0%}) "
                      "-- possivel bloqueio. Parando (sem retomar sozinho).")
                return
            time.sleep(dormir_segundos)
    finally:
        cliente.fechar()


if __name__ == "__main__":
    rodar_loop()
```

- [ ] **Step 14: Run test to verify it passes**

Run: `python -m pytest inpi/test_coleta_mercado.py -v`
Expected: PASS (7 tests)

- [ ] **Step 15: Run the full inpi/ suite (no regressions)**

Run: `python -m pytest inpi/ -q`
Expected: PASS, sem regressao (novo modulo + fix isolado do Task 2)

- [ ] **Step 16: Commit**

```bash
git add inpi/coleta_mercado.py inpi/test_coleta_mercado.py
git commit -m "feat(inpi): coleta_mercado.rodar_loop() + CLI -- loop continuo com parada limpa"
```

---

## Fora de escopo (herdado do spec, não repetido em tasks)

- Criar a credencial `INPI_PAG_LOGIN_MERCADO` de verdade no INPI — passo
  manual do usuário, só bloqueia rodar de verdade, não bloqueia codar/testar.
- Rodar `popular_nacional()` de fato (expandir pra 153k) — o código existe
  e é testado, mas só deve ser chamado quando o usuário decidir "fechar o
  escopo" (decisão de produto, não deste plano).
- Reset de itens marcados "erro" de volta pra "pendente" (retry manual) —
  não pedido; se um item falhar hoje, fica marcado "erro" e não é
  reprocessado automaticamente. Adicionar depois se necessário (YAGNI).
