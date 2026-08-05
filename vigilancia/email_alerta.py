"""Envio do resumo semanal de alertas por e-mail (Gmail SMTP, app password).

Credenciais em .env (nunca no codigo): SMTP_USER, SMTP_PASS -- ver .env.example.
LGPD: o corpo do e-mail so traz numero de processo e texto de despacho publico,
nunca dado pessoal de pessoa fisica (docs/lgpd.md).
"""

from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _html(alertas: list[dict]) -> str:
    if not alertas:
        return "<p>Nenhum alerta novo nesta execucao.</p>"
    cores = {"alta": "#c0392b", "media": "#d68910", "baixa": "#2874a6"}
    linhas = "".join(
        f'<tr><td style="color:{cores.get(a["severidade"], "#333")};font-weight:bold">'
        f'{a["severidade"].upper()}</td><td>{a["tipo"]}</td>'
        f'<td>{a.get("processo") or a.get("titular") or "-"}</td>'
        f'<td>{a["mensagem"]}</td><td>{a.get("data") or "-"}</td></tr>'
        for a in alertas
    )
    return (
        "<table border='1' cellpadding='6' cellspacing='0'>"
        "<tr><th>Severidade</th><th>Tipo</th><th>Processo/Titular</th>"
        "<th>Mensagem</th><th>Data</th></tr>" + linhas + "</table>"
    )


def montar_email(alertas: list[dict], destinatarios: list[str]) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Vigilancia INPI/EPO -- {len(alertas)} alerta(s)"
    msg["From"] = os.getenv("SMTP_USER", "")
    msg["To"] = ", ".join(destinatarios)
    msg.attach(MIMEText(_html(alertas), "html", "utf-8"))
    return msg


def enviar(alertas: list[dict], destinatarios: list[str], dry_run: bool = False) -> dict:
    """Envia o resumo de alertas. Com dry_run=True, so loga o que enviaria."""
    if not destinatarios:
        return {"enviado": False, "mensagem": "Sem destinatario configurado em config.yaml."}

    msg = montar_email(alertas, destinatarios)
    if dry_run:
        return {
            "enviado": False,
            "dry_run": True,
            "mensagem": (
                f"[dry-run] e-mail NAO enviado. Assunto={msg['Subject']!r} "
                f"destinatarios={destinatarios} alertas={len(alertas)}"
            ),
        }

    usuario, senha = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    if not usuario or not senha:
        return {
            "enviado": False,
            "erro": True,
            "mensagem": "SMTP_USER e/ou SMTP_PASS ausentes no .env -- ver .env.example.",
        }

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as servidor:
        servidor.starttls()
        servidor.login(usuario, senha)
        servidor.sendmail(usuario, destinatarios, msg.as_string())
    return {"enviado": True, "destinatarios": destinatarios, "alertas": len(alertas)}
