"""Orquestra a vigilancia semanal: reingestao -> 5 vigias -> alertas -> e-mail.

    python -m vigilancia.executar                # roda de verdade, envia e-mail
    python -m vigilancia.executar --dry-run       # roda tudo, NAO envia e-mail
    python -m vigilancia.executar --sem-reingestao --dry-run   # usa a base como esta

Agendado via scripts/instalar_agendamento.ps1: terca as 20h (pos-RPI), semanal.
O vigia 5 (exterior) poupa quota EPO rodando so na primeira terca do mes -- a
logica de "primeira terca" fica aqui, e nao em duas tarefas agendadas, porque e
mais simples de manter e de conferir (basta olhar alertas.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import yaml

from vigilancia import email_alerta, reingestao, vigias

RAIZ = Path(__file__).resolve().parent
CONFIG = RAIZ / "config.yaml"
BANCO = RAIZ / "data" / "alertas.duckdb"
ALERTAS_MD = RAIZ / "data" / "alertas.md"
ESTADO_ANUIDADES = RAIZ / "data" / "estado_anuidades.json"
ESTADO_EXTERIOR = RAIZ / "data" / "estado_exterior.json"
LOG_EXECUCAO = RAIZ / "data" / "log_execucoes.jsonl"


def carregar_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}


def _carrega_json(caminho: Path) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}


def _grava_json(caminho: Path, dado: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dado, ensure_ascii=False), encoding="utf-8")


def _con() -> duckdb.DuckDBPyConnection:
    BANCO.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(BANCO))
    con.execute("""
        CREATE TABLE IF NOT EXISTS alertas (
            id BIGINT, tipo VARCHAR, severidade VARCHAR, processo VARCHAR,
            titular VARCHAR, mensagem VARCHAR, data VARCHAR, fonte VARCHAR,
            data_corte VARCHAR, criado_em VARCHAR, visto BOOLEAN DEFAULT FALSE
        )
    """)
    return con


def _proximo_id(con: duckdb.DuckDBPyConnection) -> int:
    r = con.execute("SELECT max(id) FROM alertas").fetchone()[0]
    return (r or 0) + 1


def primeira_terca_do_mes(ref: date | None = None) -> bool:
    """True se `ref` cai na primeira terca-feira do mes (weekday()==1, dia<=7)."""
    ref = ref or date.today()
    return ref.weekday() == 1 and ref.day <= 7


def gravar_alertas(alertas: list[dict]) -> int:
    """Grava os alertas novos no DuckDB. Devolve quantos foram gravados."""
    if not alertas:
        return 0
    con = _con()
    prox = _proximo_id(con)
    agora = datetime.now(timezone.utc).isoformat()
    for i, a in enumerate(alertas):
        con.execute(
            """INSERT INTO alertas VALUES (?,?,?,?,?,?,?,?,?,?,FALSE)""",
            [prox + i, a["tipo"], a["severidade"], a.get("processo"), a.get("titular"),
             a["mensagem"], a.get("data"), a["fonte"], a.get("data_corte"), agora],
        )
    con.close()
    return len(alertas)


def gerar_markdown(alertas: list[dict], executado_em: str) -> Path:
    ALERTAS_MD.parent.mkdir(parents=True, exist_ok=True)
    linhas = [f"# Alertas de vigilancia -- {executado_em}\n"]
    if not alertas:
        linhas.append("Nenhum alerta novo nesta execucao.\n")
    else:
        por_sev = {"alta": [], "media": [], "baixa": []}
        for a in alertas:
            por_sev.setdefault(a["severidade"], []).append(a)
        for sev in ("alta", "media", "baixa"):
            itens = por_sev.get(sev, [])
            if not itens:
                continue
            linhas.append(f"\n## Severidade {sev} ({len(itens)})\n")
            for a in itens:
                alvo = a.get("processo") or a.get("titular") or "-"
                linhas.append(
                    f"- **{a['tipo']}** [{alvo}] {a['mensagem']} "
                    f"(data: {a.get('data') or '-'}, fonte: {a['fonte']}, "
                    f"corte: {a.get('data_corte') or '-'})"
                )
    ALERTAS_MD.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return ALERTAS_MD


def executar(dry_run: bool = False, sem_reingestao: bool = False,
             sem_email: bool = False, hoje: str | None = None,
             destino_dashboard: str | None = None) -> dict:
    ref = date.fromisoformat(hoje) if hoje else date.today()
    cfg = carregar_config()

    if not sem_reingestao:
        r = reingestao.reingerir(baixar=True)
        if r.get("erro"):
            _loga_execucao(sucesso=False, mensagem=r["mensagem"])
            return r

    numeros = cfg.get("carteira") or []
    titulares = cfg.get("titulares_concorrentes") or []
    ipcs = cfg.get("ipcs") or []
    destinatarios = cfg.get("email_destino") or []

    # 'desde' dos vigias 1-3: ultima execucao registrada, ou 7 dias atras na
    # primeira vez. Cada RPI sai por semana, entao 7 dias e uma janela segura.
    log_anterior = _ultima_execucao_ok()
    desde = log_anterior or (ref.fromordinal(ref.toordinal() - 7)).isoformat()

    alertas: list[dict] = []
    alertas += vigias.vigia_carteira(numeros, desde)
    alertas += vigias.vigia_concorrentes(titulares, desde)
    alertas += vigias.vigia_ipc(ipcs, desde)

    estado_anu = _carrega_json(ESTADO_ANUIDADES)
    novos_anu, estado_anu_novo = vigias.vigia_anuidades(numeros, ref.isoformat(), estado_anu)
    alertas += novos_anu
    _grava_json(ESTADO_ANUIDADES, estado_anu_novo)

    if primeira_terca_do_mes(ref):
        estado_ext = _carrega_json(ESTADO_EXTERIOR)
        novos_ext, estado_ext_novo = vigias.vigia_exterior(numeros, estado_ext)
        alertas += novos_ext
        _grava_json(ESTADO_EXTERIOR, estado_ext_novo)

    gravados = gravar_alertas(alertas)
    md = gerar_markdown(alertas, ref.isoformat())

    # Dashboard (4.3, Fase 2): painel_dados.montar() le os alertas direto do
    # BANCO (ja gravados acima), entao basta regerar o HTML -- sem precisar
    # passar a lista de alertas por parametro.
    from inpi.relatorio_html import gerar as gerar_dashboard
    dashboard = gerar_dashboard(hoje=ref.isoformat(), banco_alertas=str(BANCO),
                                 saida=destino_dashboard)

    resultado_email = (
        {"enviado": False, "mensagem": "sem_email=True"} if sem_email
        else email_alerta.enviar(alertas, destinatarios, dry_run=dry_run)
    )

    from vigilancia.sync_motherduck import sincronizar
    sync = sincronizar()
    if not sync["ok"] and not sync.get("pulado"):
        _loga_execucao(sucesso=False,
                       mensagem=f"sync MotherDuck falhou: {sync['mensagem']}")

    _loga_execucao(sucesso=True, mensagem=f"{len(alertas)} alertas, {gravados} gravados")

    return {
        "executado_em": ref.isoformat(),
        "sync_motherduck": sync,
        "desde": desde,
        "total_alertas": len(alertas),
        "gravados": gravados,
        "alertas_md": str(md),
        "dashboard": dashboard,
        "vigia_exterior_rodou": primeira_terca_do_mes(ref),
        "email": resultado_email,
        "dry_run": dry_run,
    }


def _ultima_execucao_ok() -> str | None:
    if not LOG_EXECUCAO.exists():
        return None
    ultima = None
    for linha in LOG_EXECUCAO.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if r.get("sucesso"):
            ultima = r
    return ultima["quando"].split("T")[0] if ultima else None


def _loga_execucao(sucesso: bool, mensagem: str) -> None:
    """Log de execucao -- e a base do alerta 'Task Scheduler falhou em
    silencio' (risco listado na secao 9 do plano): ausencia de entrada nova
    por >8 dias e o sinal de que a tarefa agendada parou de rodar."""
    LOG_EXECUCAO.parent.mkdir(parents=True, exist_ok=True)
    with LOG_EXECUCAO.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "quando": datetime.now(timezone.utc).isoformat(),
            "sucesso": sucesso,
            "mensagem": mensagem,
        }, ensure_ascii=False) + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description="Vigilancia autonoma INPI/EPO")
    p.add_argument("--dry-run", action="store_true", help="Roda tudo, NAO envia e-mail de verdade.")
    p.add_argument("--sem-reingestao", action="store_true", help="Nao baixa/recarrega o DuckDB.")
    p.add_argument("--sem-email", action="store_true", help="Pula o envio de e-mail por completo.")
    p.add_argument("--hoje", default=None, help="AAAA-MM-DD, para execucao reproduzivel (testes).")
    args = p.parse_args()

    r = executar(dry_run=args.dry_run, sem_reingestao=args.sem_reingestao,
                 sem_email=args.sem_email, hoje=args.hoje)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 1 if r.get("erro") else 0


if __name__ == "__main__":
    sys.exit(main())
