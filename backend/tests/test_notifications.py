"""Tests du fil de notifications in-app."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.services.notifications import notify
from conftest import verify_email

PWD = "Compliance!2026x"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def org(client: TestClient):
    email = f"notif-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": "Acme SAS", "accept_terms": True,
    })
    assert r.status_code == 201, r.text
    org_id = r.json()["memberships"][0]["organization_id"]
    verify_email(client, email)
    token = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PWD}
    ).json()["access_token"]
    return org_id, {"Authorization": f"Bearer {token}"}


def _seed(db, org_id: str, n: int) -> None:
    # Commit apres chaque insertion : `now()` de Postgres est fixe pour la
    # duree d'une transaction, donc des notifications creees dans la meme
    # transaction partageraient un created_at identique et l'ordre deviendrait
    # indetermine.
    for i in range(n):
        notify(
            db, organization_id=uuid.UUID(org_id), kind="test.event",
            title=f"Evenement {i}", body="Corps du test.",
        )
        db.commit()


def test_notifications_listed_most_recent_first(client, org):
    org_id, headers = org
    with SessionLocal() as db:
        _seed(db, org_id, 3)

    r = client.get(f"/api/v1/orgs/{org_id}/notifications", headers=headers)
    assert r.status_code == 200
    titles = [n["title"] for n in r.json()]
    assert titles == ["Evenement 2", "Evenement 1", "Evenement 0"]


def test_notifications_limit_param(client, org):
    org_id, headers = org
    with SessionLocal() as db:
        _seed(db, org_id, 5)

    r = client.get(f"/api/v1/orgs/{org_id}/notifications?limit=2", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_notification_fields_round_trip(client, org):
    org_id, headers = org
    with SessionLocal() as db:
        notify(
            db, organization_id=uuid.UUID(org_id), kind="framework.updated",
            title="RGPD a ete mis a jour", body="Le texte source a change.",
            related_framework_code="rgpd",
        )
        db.commit()

    entry = client.get(f"/api/v1/orgs/{org_id}/notifications", headers=headers).json()[0]
    assert entry["kind"] == "framework.updated"
    assert entry["related_framework_code"] == "rgpd"
    assert entry["related_audit_id"] is None


def test_notify_emails_org_members(client, org, monkeypatch):
    from app.services import notifications as notifications_service

    sent = []
    monkeypatch.setattr(notifications_service.email_service, "send_email", lambda **k: sent.append(k))

    org_id, _ = org
    with SessionLocal() as db:
        notify(
            db, organization_id=uuid.UUID(org_id), kind="test.event",
            title="Titre du test", body="Corps du test.",
        )
        db.commit()

    assert len(sent) == 1
    assert "Titre du test" in sent[0]["subject"]
    assert "Corps du test." in sent[0]["body"]


def test_notify_by_email_false_sends_nothing(client, org, monkeypatch):
    from app.services import notifications as notifications_service

    sent = []
    monkeypatch.setattr(notifications_service.email_service, "send_email", lambda **k: sent.append(k))

    org_id, _ = org
    with SessionLocal() as db:
        notify(
            db, organization_id=uuid.UUID(org_id), kind="test.event",
            title="Silencieux", body="Ne doit pas partir.", notify_by_email=False,
        )
        db.commit()

    assert sent == []


def test_notify_emails_every_active_member(client, org, monkeypatch):
    from app.services import notifications as notifications_service

    sent = []
    monkeypatch.setattr(notifications_service.email_service, "send_email", lambda **k: sent.append(k))

    org_id, headers = org
    second_email = f"notif-member-{uuid.uuid4().hex[:8]}@exemple.fr"
    client.post("/api/v1/auth/register", json={
        "email": second_email, "password": PWD, "full_name": "Autre Membre",
        "organization_name": "Org secondaire (non utilisee)", "accept_terms": True,
    })
    r = client.post(
        f"/api/v1/orgs/{org_id}/members", headers=headers,
        json={"email": second_email, "role": "viewer"},
    )
    assert r.status_code == 201, r.text
    sent.clear()  # ignorer l'e-mail de verification envoye a l'inscription ci-dessus

    with SessionLocal() as db:
        notify(
            db, organization_id=uuid.UUID(org_id), kind="test.event",
            title="Diffusion", body="Doit atteindre tout le monde.",
        )
        db.commit()

    recipients = {s["to"] for s in sent}
    assert len(sent) == 2
    assert second_email in recipients


def test_notifications_of_another_org_are_invisible(client, org):
    org_a, _ = org
    with SessionLocal() as db:
        notify(
            db, organization_id=uuid.UUID(org_a), kind="test.event",
            title="Prive", body="Ne doit pas fuiter vers une autre organisation.",
        )
        db.commit()

    email_b = f"notif-b-{uuid.uuid4().hex[:8]}@exemple.fr"
    client.post("/api/v1/auth/register", json={
        "email": email_b, "password": PWD, "full_name": "Autre Personne",
        "organization_name": "Beta SARL", "accept_terms": True,
    })
    verify_email(client, email_b)
    token_b = client.post(
        "/api/v1/auth/login", json={"email": email_b, "password": PWD}
    ).json()["access_token"]

    r = client.get(
        f"/api/v1/orgs/{org_a}/notifications",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 404  # pas membre de cette organisation
