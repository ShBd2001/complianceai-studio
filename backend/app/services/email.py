"""Envoi d'e-mails transactionnels (verification, reinitialisation).

Trois voies possibles, dans cet ordre : Brevo (API HTTP), SMTP, fichier local.
Sans rien de configure, rien ne se perd : le message est ecrit dans
STORAGE_DIR/emails/ sous forme de fichier texte horodate, lien complet en
clair.

Le SMTP seul ne suffit pas en production : les plans gratuits des
hebergeurs (Render y compris) bloquent couramment les ports sortants
25/465/587 pour lutter contre le spam. Des identifiants SMTP corrects
peuvent donc fonctionner en local et echouer silencieusement une fois
deploye, sans rapport avec leur validite — constate en conditions reelles.
Brevo (ou tout fournisseur a API HTTP) contourne ca : le trafic part en
HTTPS (443), jamais bloque. BREVO_API_KEY est donc prioritaire si present ;
SMTP reste utile en local ou chez un hebergeur qui n'a pas cette
restriction.

Un echec d'envoi ne doit jamais faire echouer la requete HTTP appelante
(l'utilisateur a deja recu la reponse attendue — 201 sur /register, reponse
generique anti-enumeration sur /password-reset) : il degrade silencieusement
vers le repli fichier, journalise pour diagnostic.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import httpx

from app.core.config import settings

logger = logging.getLogger("complianceai.email")

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


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


def _sans_injection(valeur: str) -> str:
    """Neutralise une tentative d'injection d'en-tete (CRLF) : un sujet — qui
    peut provenir d'un titre de campagne choisi par l'utilisateur, via une
    notification — ne doit jamais pouvoir introduire une ligne d'en-tete
    supplementaire (Bcc, faux expediteur...)."""
    return " ".join(valeur.splitlines()).strip()


def _send_via_brevo(to: str, subject: str, body: str) -> None:
    sender_email = settings.EMAIL_FROM or settings.SMTP_USER
    if not sender_email:
        raise RuntimeError("BREVO_API_KEY defini sans EMAIL_FROM (ni SMTP_USER en repli).")
    r = httpx.post(
        BREVO_API_URL,
        headers={"api-key": settings.BREVO_API_KEY, "Content-Type": "application/json"},
        json={
            "sender": {"email": sender_email, "name": settings.EMAIL_FROM_NAME},
            "to": [{"email": to}],
            "subject": subject,
            "textContent": body,
        },
        timeout=10,
    )
    r.raise_for_status()


def send_email(*, to: str, subject: str, body: str) -> None:
    to = _sans_injection(to)
    subject = _sans_injection(subject)

    if settings.BREVO_API_KEY:
        try:
            _send_via_brevo(to, subject, body)
            logger.info("E-mail envoye a %s via Brevo (%s).", to, subject)
            return
        except Exception:
            logger.exception("Echec de l'envoi via Brevo a %s, repli sur le fichier local.", to)
            _write_local(to, subject, body, note="Brevo en echec, voir les logs applicatifs")
            return

    if not settings.SMTP_HOST:
        path = _write_local(to, subject, body)
        logger.info("Aucun envoi configure : e-mail ecrit dans %s", path)
        return

    message = EmailMessage()
    message["From"] = _sans_injection(settings.SMTP_FROM or settings.SMTP_USER or "no-reply@localhost")
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
