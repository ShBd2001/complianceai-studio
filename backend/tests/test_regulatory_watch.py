"""Tests de la veille reglementaire (app/services/scheduler.py).

`ingest_all` est remplace par une version factice : ces tests verifient la
logique de decision (qui verifier, qui notifier), pas l'ingestion elle-meme
(deja couverte par test_audit_pipeline.py) ni un appel reseau reel.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.base import IngestionResult, RawRequirement
from app.ingestion.runner import IngestionReport, ingest
from app.main import app
from app.models.enums import Pillar, RequirementKind
from app.models.framework import Framework
from app.models.notification import Notification
from app.services import scheduler as scheduler_service

PWD = "Compliance!2026x"


class FakeRgpdConnector:
    code = "rgpd"

    def fetch(self) -> IngestionResult:
        req = RawRequirement(
            reference="Article 32", title="Securite du traitement",
            body="Mesures de securite.",
            kind=RequirementKind.ARTICLE, ordering=1,
            source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
        )
        return IngestionResult(
            code="rgpd", name="Reglement general sur la protection des donnees",
            pillar=Pillar.PRIVACY, authority="Parlement europeen et Conseil",
            source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            license="Decision 2011/833/UE", celex_id="32016R0679",
            version_label="2016/679", effective_date=date(2018, 5, 25),
            requirements=[req], raw_text=f"Article 32 {req.body}",
        )


@pytest.fixture(scope="module")
def framework_ready():
    with SessionLocal() as db:
        report = ingest(db, FakeRgpdConnector(), force=True)
        db.commit()
        assert report.status in {"created", "updated"}
        yield report


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def org(client: TestClient):
    email = f"watch-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": "Acme SAS", "accept_terms": True,
    })
    assert r.status_code == 201, r.text
    org_id = r.json()["memberships"][0]["organization_id"]
    token = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PWD}
    ).json()["access_token"]
    return org_id, {"Authorization": f"Bearer {token}"}


def _framework(db) -> Framework:
    fw = db.scalar(select(Framework).where(Framework.code == "rgpd"))
    assert fw is not None
    return fw


def test_watch_notifies_orgs_with_audits_on_real_change(client, org, framework_ready, monkeypatch):
    org_id, headers = org
    client.post(
        f"/api/v1/orgs/{org_id}/audits", headers=headers,
        json={"title": "Audit RGPD", "framework": "rgpd"},
    )

    monkeypatch.setattr(
        scheduler_service, "ingest_all",
        lambda db, codes=None, force=False: [
            IngestionReport(code="rgpd", status="updated", version_label="2027/1")
        ],
    )

    with SessionLocal() as db:
        fw = _framework(db)
        fw.watch_checked_at = None
        db.commit()

        scheduler_service._run_regulatory_watch(db)
        db.commit()

        db.refresh(fw)
        assert fw.watch_checked_at is not None

        notif = db.scalar(
            select(Notification).where(
                Notification.organization_id == uuid.UUID(org_id),
                Notification.kind == "framework.updated",
            )
        )
        assert notif is not None
        assert notif.related_framework_code == "rgpd"


def test_watch_updates_checked_at_without_notifying_when_unchanged(client, org, framework_ready, monkeypatch):
    org_id, headers = org
    client.post(
        f"/api/v1/orgs/{org_id}/audits", headers=headers,
        json={"title": "Audit RGPD", "framework": "rgpd"},
    )

    monkeypatch.setattr(
        scheduler_service, "ingest_all",
        lambda db, codes=None, force=False: [
            IngestionReport(code="rgpd", status="unchanged", version_label="2016/679")
        ],
    )

    with SessionLocal() as db:
        fw = _framework(db)
        fw.watch_checked_at = None
        db.commit()

        scheduler_service._run_regulatory_watch(db)
        db.commit()

        db.refresh(fw)
        assert fw.watch_checked_at is not None

        notif = db.scalar(
            select(Notification).where(
                Notification.organization_id == uuid.UUID(org_id),
                Notification.kind == "framework.updated",
            )
        )
        assert notif is None


def test_watch_skips_frameworks_checked_recently(framework_ready, monkeypatch):
    """Regression du bug releve en revue : le seuil doit se baser sur la
    derniere VERIFICATION, pas sur la derniere date de changement reel."""
    called: list[list[str] | None] = []
    monkeypatch.setattr(
        scheduler_service, "ingest_all",
        lambda db, codes=None, force=False: (called.append(codes) or []),
    )

    with SessionLocal() as db:
        fw = _framework(db)
        fw.watch_checked_at = datetime.now(timezone.utc)  # verifie a l'instant
        db.commit()

        scheduler_service._run_regulatory_watch(db)
        db.commit()

    assert not any(c and "rgpd" in c for c in called)


def test_watch_rechecks_framework_past_the_interval(framework_ready, monkeypatch):
    from app.core.config import settings

    called: list[list[str] | None] = []
    monkeypatch.setattr(
        scheduler_service, "ingest_all",
        lambda db, codes=None, force=False: (
            called.append(codes)
            or [IngestionReport(code="rgpd", status="unchanged", version_label="2016/679")]
        ),
    )

    with SessionLocal() as db:
        fw = _framework(db)
        fw.watch_checked_at = datetime.now(timezone.utc) - timedelta(
            hours=settings.REGULATORY_WATCH_INTERVAL_HOURS + 1
        )
        db.commit()

        scheduler_service._run_regulatory_watch(db)
        db.commit()

    assert any(c and "rgpd" in c for c in called)
