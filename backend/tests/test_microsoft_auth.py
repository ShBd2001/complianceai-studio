"""Tests de « Se connecter avec Microsoft » (Entra ID -- endpoints
/auth/microsoft/login et /auth/microsoft/register).

Le jeton Microsoft (signature, audience, forme de l'emetteur) n'est jamais
genere ici : comme pour Google (voir test_google_auth.py) et pour EUR-Lex
(voir FakeConnector dans test_audit_pipeline.py), un test ne doit jamais
dependre de la disponibilite d'un service externe. decode_microsoft_id_token
est donc remplace par un decodeur factice qui retourne des claims connus --
la verification cryptographique elle-meme (signature RS256, JWKS, audience)
vit dans app/core/security.py::decode_microsoft_id_token et n'a pas de
branche metier a tester ici.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

PWD = "Compliance!2026x"


def _email() -> str:
    return f"microsoft-{uuid.uuid4().hex[:10]}@exemple.fr"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _claims(
    email: str | None = None,
    preferred_username: str | None = None,
    name: str = "Sarah Test",
) -> dict:
    tenant_id = str(uuid.uuid4())
    claims: dict = {
        "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        "aud": "test-client-id",
        "sub": "microsoft-uid-" + uuid.uuid4().hex[:8],
        "tid": tenant_id,
        "name": name,
    }
    if email is not None:
        claims["email"] = email
    if preferred_username is not None:
        claims["preferred_username"] = preferred_username
    return claims


def _mock_microsoft(monkeypatch: pytest.MonkeyPatch, claims: dict | None) -> None:
    monkeypatch.setattr("app.api.v1.auth.decode_microsoft_id_token", lambda token: claims)


def test_microsoft_register_creates_account_and_logs_in(client, monkeypatch):
    email = _email()
    _mock_microsoft(monkeypatch, _claims(email=email))

    r = client.post("/api/v1/auth/microsoft/register", json={
        "id_token": "jeton-factice", "organization_name": "Cabinet Microsoft SAS",
        "accept_terms": True,
    })
    assert r.status_code == 201, r.text
    jeton = r.json()["access_token"]
    assert jeton

    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton}"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == email
    assert r.json()["email_verified_at"] is not None
    assert r.json()["memberships"][0]["role"] == "owner"


def test_microsoft_register_falls_back_to_preferred_username(client, monkeypatch):
    """Le claim `email` n'est pas garanti chez Microsoft (pas d'equivalent au
    `email_verified` de Google) : pour un compte professionnel, le UPN
    (`preferred_username`) est l'identifiant fiable, controle par
    l'annuaire de l'organisation."""
    upn = _email()
    _mock_microsoft(monkeypatch, _claims(preferred_username=upn))

    r = client.post("/api/v1/auth/microsoft/register", json={
        "id_token": "jeton-factice", "organization_name": "Cabinet UPN SAS",
        "accept_terms": True,
    })
    assert r.status_code == 201, r.text

    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert r.json()["email"] == upn


def test_microsoft_register_refuses_claims_without_usable_identifier(client, monkeypatch):
    """Ni `email` ni `preferred_username` exploitable (absent, ou sans
    '@') : le jeton est traite comme invalide plutot que de risquer de
    creer un compte sur un identifiant qui n'est pas une adresse."""
    _mock_microsoft(monkeypatch, _claims())
    r = client.post("/api/v1/auth/microsoft/register", json={
        "id_token": "jeton-factice", "organization_name": "Cabinet SAS", "accept_terms": True,
    })
    assert r.status_code == 401


def test_microsoft_register_refuses_existing_email(client, monkeypatch):
    email = _email()
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": "Acme SAS", "accept_terms": True,
    })
    assert r.status_code == 201, r.text

    _mock_microsoft(monkeypatch, _claims(email=email))
    r = client.post("/api/v1/auth/microsoft/register", json={
        "id_token": "jeton-factice", "organization_name": "Autre SAS", "accept_terms": True,
    })
    assert r.status_code == 409


def test_microsoft_register_refuses_without_consent(client, monkeypatch):
    email = _email()
    _mock_microsoft(monkeypatch, _claims(email=email))
    r = client.post("/api/v1/auth/microsoft/register", json={
        "id_token": "jeton-factice", "organization_name": "Cabinet SAS", "accept_terms": False,
    })
    assert r.status_code == 422


def test_microsoft_login_refuses_invalid_token(client, monkeypatch):
    _mock_microsoft(monkeypatch, None)
    r = client.post("/api/v1/auth/microsoft/login", json={"id_token": "jeton-invalide"})
    assert r.status_code == 401


def test_microsoft_login_requires_existing_account(client, monkeypatch):
    email = _email()
    _mock_microsoft(monkeypatch, _claims(email=email))
    r = client.post("/api/v1/auth/microsoft/login", json={"id_token": "jeton-factice"})
    assert r.status_code == 404
    assert "aucun compte" in r.json()["detail"].lower()


def test_microsoft_login_signs_in_existing_account_and_verifies_it(client, monkeypatch):
    email = _email()
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": "Acme SAS", "accept_terms": True,
    })
    assert r.status_code == 201, r.text
    # Pas de verify_email() ici : c'est precisement le cas qu'on teste.

    r = client.post("/api/v1/auth/login", json={"email": email, "password": PWD})
    assert r.status_code == 403  # non verifiee : bloquee par mot de passe

    _mock_microsoft(monkeypatch, _claims(email=email))
    r = client.post("/api/v1/auth/microsoft/login", json={"id_token": "jeton-factice"})
    assert r.status_code == 200, r.text
    jeton = r.json()["access_token"]

    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton}"})
    assert r.json()["email_verified_at"] is not None
