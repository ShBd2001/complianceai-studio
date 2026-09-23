"""Tests de « Se connecter avec Google » (OpenID Connect -- endpoints
/auth/google/login et /auth/google/register).

Le jeton Google (signature, audience, emetteur) n'est jamais genere ici :
comme pour EUR-Lex (voir FakeConnector dans test_audit_pipeline.py), un
test ne doit jamais dependre de la disponibilite d'un service externe.
decode_google_id_token est donc remplace par un decodeur factice qui
retourne des claims connus -- la verification cryptographique elle-meme
(signature RS256, JWKS, audience, emetteur) vit dans
app/core/security.py::decode_google_id_token et n'a pas de branche
metier a tester ici.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

PWD = "Compliance!2026x"


def _email() -> str:
    return f"google-{uuid.uuid4().hex[:10]}@exemple.fr"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _claims(email: str, verified: bool = True, name: str = "Sarah Test") -> dict:
    return {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id",
        "sub": "google-uid-" + uuid.uuid4().hex[:8],
        "email": email,
        "email_verified": verified,
        "name": name,
    }


def _mock_google(monkeypatch: pytest.MonkeyPatch, claims: dict | None) -> None:
    monkeypatch.setattr("app.api.v1.auth.decode_google_id_token", lambda token: claims)


def test_google_register_creates_account_and_logs_in(client, monkeypatch):
    email = _email()
    _mock_google(monkeypatch, _claims(email))

    r = client.post("/api/v1/auth/google/register", json={
        "id_token": "jeton-factice", "organization_name": "Cabinet Google SAS",
        "accept_terms": True,
    })
    assert r.status_code == 201, r.text
    jeton = r.json()["access_token"]
    assert jeton

    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton}"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == email
    assert r.json()["email_verified_at"] is not None  # deja prouve par Google
    assert r.json()["memberships"][0]["role"] == "owner"


def test_google_register_refuses_existing_email(client, monkeypatch):
    email = _email()
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": "Acme SAS", "accept_terms": True,
    })
    assert r.status_code == 201, r.text

    _mock_google(monkeypatch, _claims(email))
    r = client.post("/api/v1/auth/google/register", json={
        "id_token": "jeton-factice", "organization_name": "Autre SAS", "accept_terms": True,
    })
    assert r.status_code == 409


def test_google_register_refuses_without_consent(client, monkeypatch):
    email = _email()
    _mock_google(monkeypatch, _claims(email))
    r = client.post("/api/v1/auth/google/register", json={
        "id_token": "jeton-factice", "organization_name": "Cabinet SAS", "accept_terms": False,
    })
    assert r.status_code == 422


def test_google_register_refuses_unverified_email(client, monkeypatch):
    email = _email()
    _mock_google(monkeypatch, _claims(email, verified=False))
    r = client.post("/api/v1/auth/google/register", json={
        "id_token": "jeton-factice", "organization_name": "Cabinet SAS", "accept_terms": True,
    })
    assert r.status_code == 401


def test_google_login_refuses_invalid_token(client, monkeypatch):
    _mock_google(monkeypatch, None)
    r = client.post("/api/v1/auth/google/login", json={"id_token": "jeton-invalide"})
    assert r.status_code == 401


def test_google_login_requires_existing_account(client, monkeypatch):
    email = _email()
    _mock_google(monkeypatch, _claims(email))
    r = client.post("/api/v1/auth/google/login", json={"id_token": "jeton-factice"})
    assert r.status_code == 404
    assert "aucun compte" in r.json()["detail"].lower()


def test_google_login_signs_in_existing_account_and_verifies_it(client, monkeypatch):
    """Un compte cree par mot de passe mais jamais verifie reste bloque a la
    connexion normale -- mais Google vient de reprouver la propriete de
    l'adresse : la connexion Google doit reussir et lever le blocage au
    passage, plutot que de laisser la personne coincee entre deux methodes
    de connexion pour le meme compte."""
    email = _email()
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": "Acme SAS", "accept_terms": True,
    })
    assert r.status_code == 201, r.text
    # Pas de verify_email() ici : c'est precisement le cas qu'on teste.

    r = client.post("/api/v1/auth/login", json={"email": email, "password": PWD})
    assert r.status_code == 403  # non verifiee : bloquee par mot de passe

    _mock_google(monkeypatch, _claims(email))
    r = client.post("/api/v1/auth/google/login", json={"id_token": "jeton-factice"})
    assert r.status_code == 200, r.text
    jeton = r.json()["access_token"]

    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton}"})
    assert r.json()["email_verified_at"] is not None
