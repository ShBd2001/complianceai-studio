"""Tests d'integration du parcours d'authentification et de l'isolation multi-tenant.

Ces tests constituent une partie des preuves attendues par le referentiel
(CC1.2 : "le code ne presente pas de faille de securite connue").
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from conftest import verify_email

PWD = "Compliance!2026x"


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@exemple.fr"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient, email: str, org: str = "Acme SAS") -> dict:
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": PWD,
            "full_name": "Sarah Test",
            "organization_name": org,
            "accept_terms": True,
        },
    )
    assert r.status_code == 201, r.text
    verify_email(client, email)
    return r.json()


def _login(client: TestClient, email: str) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PWD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
def test_register_creates_user_org_and_owner_membership(client):
    data = _register(client, _email())
    assert data["is_active"] is True
    assert data["email_verified_at"] is None  # verification requise
    assert len(data["memberships"]) == 1
    assert data["memberships"][0]["role"] == "owner"


def test_weak_password_is_rejected(client):
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": _email(), "password": "azerty", "full_name": "Sarah Test",
            "organization_name": "Acme SAS", "accept_terms": True,
        },
    )
    assert r.status_code == 422


def test_terms_must_be_accepted(client):
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": _email(), "password": PWD, "full_name": "Sarah Test",
            "organization_name": "Acme SAS", "accept_terms": False,
        },
    )
    assert r.status_code == 422


def test_duplicate_email_conflicts(client):
    email = _email()
    _register(client, email)
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": PWD, "full_name": "Sarah Test",
            "organization_name": "Acme SAS", "accept_terms": True,
        },
    )
    assert r.status_code == 409


def test_login_sets_httponly_refresh_cookie(client):
    email = _email()
    _register(client, email)
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PWD})
    assert r.status_code == 200
    raw_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in raw_cookie
    assert "samesite=strict" in raw_cookie


def test_wrong_password_returns_generic_401(client):
    email = _email()
    _register(client, email)
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "Mauvais!2026x"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Identifiants invalides."


def test_unknown_email_returns_same_message(client):
    r = client.post("/api/v1/auth/login", json={"email": _email(), "password": PWD})
    assert r.status_code == 401
    assert r.json()["detail"] == "Identifiants invalides."  # pas d'enumeration


def test_protected_route_requires_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers=_auth("faux.jeton.abc")).status_code == 401


def test_refresh_rotates_and_old_token_is_rejected(client):
    email = _email()
    _register(client, email)
    _login(client, email)

    old = client.cookies.get("cai_refresh")
    r1 = client.post("/api/v1/auth/refresh")
    assert r1.status_code == 200
    new = client.cookies.get("cai_refresh")
    assert new != old  # rotation effective

    # Rejeu de l'ancien jeton -> revocation de toute la famille
    replay = TestClient(app)
    replay.cookies.set("cai_refresh", old)
    assert replay.post("/api/v1/auth/refresh").status_code == 401
    # la session courante est desormais morte elle aussi
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_revokes_session(client):
    email = _email()
    _register(client, email)
    _login(client, email)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_account_locks_after_repeated_failures(client):
    email = _email()
    _register(client, email)
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"email": email, "password": "Faux!2026xyz"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PWD})
    assert r.status_code == 423


# --------------------------------------------------------------------------
# Isolation multi-tenant
# --------------------------------------------------------------------------
def test_user_cannot_reach_another_organization(client):
    email_a, email_b = _email(), _email()
    org_a = _register(client, email_a, "Alpha SARL")
    _register(client, email_b, "Beta SARL")

    org_a_id = org_a["memberships"][0]["organization_id"]
    token_b = _login(client, email_b)

    r = client.get(f"/api/v1/orgs/{org_a_id}", headers=_auth(token_b))
    # 404 et non 403 : on ne revele pas l'existence de l'organisation
    assert r.status_code == 404


def test_viewer_cannot_add_members(client):
    owner_email, viewer_email = _email(), _email()
    owner = _register(client, owner_email, "Gamma SAS")
    _register(client, viewer_email, "Delta SAS")
    org_id = owner["memberships"][0]["organization_id"]

    token_owner = _login(client, owner_email)
    r = client.post(
        f"/api/v1/orgs/{org_id}/members",
        json={"email": viewer_email, "role": "viewer"},
        headers=_auth(token_owner),
    )
    assert r.status_code == 201

    token_viewer = _login(client, viewer_email)
    r = client.post(
        f"/api/v1/orgs/{org_id}/members",
        json={"email": owner_email, "role": "admin"},
        headers=_auth(token_viewer),
    )
    assert r.status_code == 403  # RBAC applique


def test_last_owner_cannot_be_removed(client):
    email = _email()
    data = _register(client, email, "Omega SA")
    org_id = data["memberships"][0]["organization_id"]
    token = _login(client, email)
    r = client.delete(f"/api/v1/orgs/{org_id}/members/{data['id']}", headers=_auth(token))
    assert r.status_code == 409


def test_activity_log_records_login(client):
    email = _email()
    data = _register(client, email, "Sigma SAS")
    org_id = data["memberships"][0]["organization_id"]
    token = _login(client, email)
    r = client.get(f"/api/v1/orgs/{org_id}/activity", headers=_auth(token))
    assert r.status_code == 200
    actions = {e["action"] for e in r.json()}
    assert "org.created" in actions or "user.registered" in actions


# --------------------------------------------------------------------------
# RGPD
# --------------------------------------------------------------------------
def test_data_export_contains_expected_sections(client):
    email = _email()
    _register(client, email)
    token = _login(client, email)
    r = client.get("/api/v1/privacy/export", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"identite", "organisations", "consentements", "sessions"}
    assert body["identite"]["email"] == email
    assert body["consentements"][0]["finalite"] == "terms_of_service"


def test_data_export_serializes_a_real_session_ip(client):
    """Regression : TestClient ne fournit jamais une IP valide (voir
    activity.client_ip), donc ip_address reste NULL et le bug ne se voit
    jamais avec la seule connexion de _login. La colonne est de type INET :
    psycopg la deserialise en objet ipaddress.IPv4Address, non serialisable
    par Pydantic tel quel — reproduit ici en forcant une vraie IP en base,
    comme le ferait un serveur reel derriere une requete HTTP normale."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.user import UserSession

    email = _email()
    _register(client, email)
    token = _login(client, email)

    with SessionLocal() as db:
        session = db.scalar(select(UserSession).order_by(UserSession.created_at.desc()))
        session.ip_address = "203.0.113.42"
        db.commit()

    r = client.get("/api/v1/privacy/export", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["sessions"][0]["ip"] == "203.0.113.42"


def test_owner_cannot_delete_account_without_transferring(client):
    email = _email()
    _register(client, email, "Tau SAS")
    token = _login(client, email)
    r = client.delete("/api/v1/privacy/me", headers=_auth(token))
    assert r.status_code == 409


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "X-Request-ID" in r.headers
