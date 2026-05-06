"""Envoi d'e-mails transactionnels (verification, reinitialisation).

Sans SMTP configure (SMTP_HOST vide — le defaut), rien ne se perd : le
message est ecrit dans STORAGE_DIR/emails/ sous forme de fichier texte
horodate, lien complet en clair. Des que SMTP_HOST est renseigne, l'envoi
devient reel via smtplib (bibliotheque standard, aucune nouvelle dependance).

Un echec d'envoi SMTP ne doit jamais faire echouer la requete HTTP appelante
(l'utilisateur a deja recu la reponse attendue — 201 sur /register, reponse
generique anti-enumeration sur /password-reset) : il degrade silencieusement
vers le meme repli fichier, journalise pour diagnostic.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger("complianceai.email")


def _dropbox_path(to: str) -> Path:
    root = Path(settings.STORAGE_DIR) / "emails"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    safe_to = "".join(c if c.isalnum() or c in "@.-_" else "_" for c in to)
    return root / f"{stamp}_{safe_to}.txt"


def _write_local(to: str, subject: str, body: str, *, note: str = "") -> Path:
    path = _dropbox_path(to)
    header = f"A : {to}\nObjet : {subject}\nDate : {datetime.now(timezone.utc).isoformat()}\n"
    if note:
        header += f"({note})\n"
    path.write_text(f"{header}\n{body}\n", encoding="utf-8")
    return path


def send_email(*, to: str, subject: str, body: str) -> None:
    if not settings.SMTP_HOST:
        path = _write_local(to, subject, body)
        logger.info("SMTP non configure : e-mail ecrit dans %s", path)
        return

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM or settings.SMTP_USER or "no-reply@localhost"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        if settings.SMTP_USE_SSL:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
                if settings.SMTP_USER:
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
                if settings.SMTP_USE_TLS:
                    smtp.starttls()
                if settings.SMTP_USER:
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
                smtp.send_message(message)
        logger.info("E-mail envoye a %s (%s).", to, subject)
    except Exception:
        logger.exception("Echec de l'envoi SMTP a %s, repli sur le fichier local.", to)
        _write_local(to, subject, body, note="SMTP en echec, voir les logs applicatifs")
