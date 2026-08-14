"""Tests du service d'e-mail transactionnel et de son branchement dans
l'authentification (verification d'adresse, reinitialisation de mot de passe).
"""

import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import email as email_service

PWD = "Compliance!2026x"
NEW_PWD = "NouveauMdp!2026x"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _email() -> str:
    return f"mail-{uuid.uuid4().hex[:10]}@exemple.fr"


def _extract_token(body: str, param: str) -> str:
    match = re.search(rf"{param}=([^\s&]+)", body)
    assert match, f"lien absent du corps de l'e-mail : {body!r}"
    return match.group(1)


# --------------------------------------------------------------------------
# Service bas niveau
# --------------------------------------------------------------------------
def test_send_email_without_smtp_writes_local_file(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "SMTP_HOST", None)

    email_service.send_email(to="test@exemple.fr", subject="Objet", body="Contenu du message.")

    fichiers = list((tmp_path / "emails").glob("*.txt"))
    assert len(fichiers) == 1
    contenu = fichiers[0].read_text(encoding="utf-8")
    assert "test@exemple.fr" in contenu
    assert "Contenu du message." in contenu


def test_send_email_via_smtp_calls_smtplib(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.exemple.fr")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_USER", "bot@exemple.fr")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(settings, "SMTP_USE_TLS", True)
    monkeypatch.setattr(settings, "SMTP_USE_SSL", False)

    calls = {"starttls": 0, "login": None, "sent": None, "host": None}

    class FakeSMTP:
        def __init__(self, host, port, timeout=10):
            calls["host"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            calls["starttls"] += 1

        def login(self, user, password):
            calls["login"] = (user, password)

        def send_message(self, message):
            calls["sent"] = message

    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)

    email_service.send_email(to="dest@exemple.fr", subject="Sujet", body="Corps.")

    assert calls["host"] == ("smtp.exemple.fr", 587)
    assert calls["starttls"] == 1
    assert calls["login"] == ("bot@exemple.fr", "secret")
    assert calls["sent"]["To"] == "dest@exemple.fr"
    assert calls["sent"]["Subject"] == "Sujet"
    # Aucun repli fichier quand l'envoi reussit.
    assert not (tmp_path / "emails").exists()


def test_send_email_strips_header_injection_from_subject(monkeypatch, tmp_path):
    """Un sujet peut provenir d'un titre de campagne choisi par l'utilisateur
    (via une notification) : un retour a la ligne ne doit jamais pouvoir
    introduire une ligne d'en-tete supplementaire (Bcc, faux expediteur...)."""
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "SMTP_HOST", None)

    email_service.send_email(
        to="dest@exemple.fr",
        subject="Sujet légitime\r\nBcc: attaquant@exemple.fr",
        body="Corps.",
    )

    fichiers = list((tmp_path / "emails").glob("*.txt"))
    lignes = fichiers[0].read_text(encoding="utf-8").splitlines()
    ligne_objet = next(l for l in lignes if l.startswith("Objet :"))
    assert ligne_objet == "Objet : Sujet légitime Bcc: attaquant@exemple.fr"


def test_send_email_via_smtp_strips_header_injection_from_subject(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.exemple.fr")

    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=10):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, message):
            captured["message"] = message

    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)

    email_service.send_email(
        to="dest@exemple.fr",
        subject="Sujet légitime\r\nBcc: attaquant@exemple.fr",
        body="Corps.",
    )

    subject = str(captured["message"]["Subject"])
    assert "\n" not in subject
    assert "\r" not in subject
    # Le contenu injecte reste visible mais neutralise sur une seule ligne :
    # il ne peut plus etre interprete comme un en-tete Bcc distinct.
    assert "Bcc: attaquant@exemple.fr" in subject


def test_send_email_falls_back_to_file_on_smtp_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.exemple.fr")

    class FailingSMTP:
        def __init__(self, *a, **k):
            raise OSError("connexion refusee")

    monkeypatch.setattr(email_service.smtplib, "SMTP", FailingSMTP)

    # Ne doit pas lever : l'appelant (une route HTTP) ne doit jamais echouer
    # a cause d'un SMTP en panne.
    email_service.send_email(to="dest@exemple.fr", subject="Sujet", body="Corps.")

    fichiers = list((tmp_path / "emails").glob("*.txt"))
    assert len(fichiers) == 1


# --------------------------------------------------------------------------
# Parcours complet via l'API
# --------------------------------------------------------------------------
def test_register_sends_verification_email_and_link_works(client, monkeypatch):
    sent = []
    monkeypatch.setattr(email_service, "send_email", lambda **kwargs: sent.append(kwargs))

    email = _email()
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": "Acme SAS", "accept_terms": True,
    })
    assert r.status_code == 201, r.text
    assert r.json()["email_verified_at"] is None

    assert len(sent) == 1
    assert sent[0]["to"] == email
    assert "vérifi" in sent[0]["subject"].lower()
    token = _extract_token(sent[0]["body"], "verify_email")

    r = client.post(f"/api/v1/auth/verify-email?token={token}")
    assert r.status_code == 204

    token_login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PWD}
    ).json()["access_token"]
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_login}"}
    ).json()
    assert me["email_verified_at"] is not None


def test_verify_email_rejects_reused_token(client, monkeypatch):
    sent = []
    monkeypatch.setattr(email_service, "send_email", lambda **kwargs: sent.append(kwargs))

    email = _email()
    client.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": "Acme SAS", "accept_terms": True,
    })
    token = _extract_token(sent[0]["body"], "verify_email")

    assert client.post(f"/api/v1/auth/verify-email?token={token}").status_code == 204
    assert client.post(f"/api/v1/auth/verify-email?token={token}").status_code == 400


def test_password_reset_full_round_trip(client, monkeypatch):
    sent = []
    monkeypatch.setattr(email_service, "send_email", lambda **kwargs: sent.append(kwargs))

    email = _email()
    client.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": "Acme SAS", "accept_terms": True,
    })
    sent.clear()  # ignorer l'e-mail de verification envoye a l'inscription

    r = client.post("/api/v1/auth/password-reset", json={"email": email})
    assert r.status_code == 202
    assert len(sent) == 1
    assert "réinitialisation" in sent[0]["subject"].lower()
    token = _extract_token(sent[0]["body"], "reset_password")

    r = client.post("/api/v1/auth/password-reset/confirm", json={
        "token": token, "new_password": NEW_PWD,
    })
    assert r.status_code == 204

    # L'ancien mot de passe ne fonctionne plus, le nouveau oui.
    assert client.post(
        "/api/v1/auth/login", json={"email": email, "password": PWD}
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/login", json={"email": email, "password": NEW_PWD}
    ).status_code == 200


def test_password_reset_unknown_email_sends_nothing(client, monkeypatch):
    """Pas d'enumeration : la reponse est identique, mais aucun e-mail ne part
    pour une adresse qui n'a pas de compte."""
    sent = []
    monkeypatch.setattr(email_service, "send_email", lambda **kwargs: sent.append(kwargs))

    r = client.post("/api/v1/auth/password-reset", json={"email": _email()})
    assert r.status_code == 202
    assert sent == []
