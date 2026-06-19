"""Tests des campagnes d'audit recurrentes (planification).

Le referentiel est injecte localement (FakeConnector), comme dans
test_audit_pipeline.py : un test ne doit jamais dependre d'un service externe.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.base import IngestionResult, RawRequirement
from app.ingestion.runner import ingest
from app.main import app
from app.models.audit import Audit, Document
from app.models.enums import Framework as FrameworkCode
from app.models.enums import Pillar, RequirementKind, ScheduleCadence
from app.models.notification import Notification
from app.models.scheduling import AuditSchedule
from app.services.scheduling import compute_next_run, run_due_schedules, run_schedule
from conftest import verify_email

PWD = "Compliance!2026x"

POLICY = (
    "Politique de securite — Acme SAS\n\n"
    "Un registre des activites de traitement est tenu a jour. Les donnees "
    "sont chiffrees au repos et en transit. En cas de violation, l'autorite "
    "de controle est notifiee dans les meilleurs delais."
)


class FakeRgpdConnector:
    code = "rgpd"

    def __init__(self, body_suffix: str = "") -> None:
        self.body_suffix = body_suffix

    def fetch(self) -> IngestionResult:
        req = RawRequirement(
            reference="Article 32", title="Securite du traitement",
            body="Mesures de securite techniques et organisationnelles." + self.body_suffix,
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
    email = f"sched-{uuid.uuid4().hex[:8]}@exemple.fr"
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


def _completed_audit(client: TestClient, org, framework_ready) -> str:
    org_id, headers = org
    audit_id = client.post(
        f"/api/v1/orgs/{org_id}/audits", headers=headers,
        json={"title": "Audit planifiable", "framework": "rgpd"},
    ).json()["id"]
    client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/documents", headers=headers,
        files={"file": ("politique.txt", POLICY.encode("utf-8"), "text/plain")},
    )
    run = client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/run", headers=headers).json()
    assert run["status"] == "completed", run
    return audit_id


# --------------------------------------------------------------------------
# compute_next_run — pas de DB, logique pure
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cadence,jours", [
    (ScheduleCadence.WEEKLY, 7),
    (ScheduleCadence.MONTHLY, 30),
    (ScheduleCadence.QUARTERLY, 91),
])
def test_compute_next_run(cadence, jours):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert compute_next_run(cadence, base) == base + timedelta(days=jours)


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
def test_schedule_refused_before_completion(client, org, framework_ready):
    org_id, headers = org
    audit_id = client.post(
        f"/api/v1/orgs/{org_id}/audits", headers=headers,
        json={"title": "Brouillon", "framework": "rgpd"},
    ).json()["id"]

    r = client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/schedule",
        headers=headers, json={"cadence": "weekly"},
    )
    assert r.status_code == 409


def test_schedule_create_update_get_cancel(client, org, framework_ready):
    org_id, headers = org
    audit_id = _completed_audit(client, org, framework_ready)

    r = client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/schedule",
        headers=headers, json={"cadence": "weekly"},
    )
    assert r.status_code == 201, r.text
    schedule_id = r.json()["id"]
    assert r.json()["is_active"] is True
    assert r.json()["cadence"] == "weekly"
    assert r.json()["framework"] == "rgpd"

    # Un second POST met a jour la planification existante (une seule par campagne)
    # plutot que d'en creer une autre.
    r = client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/schedule",
        headers=headers, json={"cadence": "monthly"},
    )
    assert r.status_code == 201
    assert r.json()["id"] == schedule_id
    assert r.json()["cadence"] == "monthly"

    r = client.get(f"/api/v1/orgs/{org_id}/audits/{audit_id}/schedule", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == schedule_id

    r = client.delete(f"/api/v1/orgs/{org_id}/audits/{audit_id}/schedule", headers=headers)
    assert r.status_code == 204

    # Toujours consultable (pas 404) pour que l'interface puisse proposer de
    # la reactiver, mais marquee inactive.
    r = client.get(f"/api/v1/orgs/{org_id}/audits/{audit_id}/schedule", headers=headers)
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_schedule_without_prior_call_gives_404(client, org, framework_ready):
    org_id, headers = org
    audit_id = _completed_audit(client, org, framework_ready)
    r = client.get(f"/api/v1/orgs/{org_id}/audits/{audit_id}/schedule", headers=headers)
    assert r.status_code == 404


def test_schedule_of_another_org_is_invisible(client, org, framework_ready):
    org_a, headers_a = org
    audit_id = _completed_audit(client, org, framework_ready)
    client.post(
        f"/api/v1/orgs/{org_a}/audits/{audit_id}/schedule",
        headers=headers_a, json={"cadence": "weekly"},
    )

    email_b = f"sched-b-{uuid.uuid4().hex[:8]}@exemple.fr"
    client.post("/api/v1/auth/register", json={
        "email": email_b, "password": PWD, "full_name": "Autre Personne",
        "organization_name": "Beta SARL", "accept_terms": True,
    })
    verify_email(client, email_b)
    token_b = client.post(
        "/api/v1/auth/login", json={"email": email_b, "password": PWD}
    ).json()["access_token"]

    r = client.get(
        f"/api/v1/orgs/{org_a}/audits/{audit_id}/schedule",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------
# Service : clonage, execution, desactivation
# --------------------------------------------------------------------------
def test_run_schedule_clones_documents_and_notifies(client, org, framework_ready):
    org_id, headers = org
    audit_id = _completed_audit(client, org, framework_ready)
    client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/schedule",
        headers=headers, json={"cadence": "weekly"},
    )

    with SessionLocal() as db:
        schedule = db.scalar(
            select(AuditSchedule).where(AuditSchedule.source_audit_id == uuid.UUID(audit_id))
        )
        source_docs = list(
            db.scalars(select(Document).where(Document.audit_id == schedule.source_audit_id))
        )
        assert len(source_docs) == 1

        before_next_run = schedule.next_run_at
        clone = run_schedule(db, schedule)
        db.commit()

        assert clone is not None
        assert clone.id != schedule.source_audit_id
        assert clone.organization_id == uuid.UUID(org_id)
        assert clone.status.value == "completed"

        clone_docs = list(db.scalars(select(Document).where(Document.audit_id == clone.id)))
        assert len(clone_docs) == 1
        assert clone_docs[0].sha256 == source_docs[0].sha256
        assert clone_docs[0].id != source_docs[0].id  # ligne distincte, meme contenu

        db.refresh(schedule)
        assert schedule.last_run_audit_id == clone.id
        assert schedule.next_run_at > before_next_run

        notif = db.scalar(
            select(Notification).where(
                Notification.organization_id == uuid.UUID(org_id),
                Notification.kind == "audit_schedule.completed",
            )
        )
        assert notif is not None
        assert notif.related_audit_id == clone.id


def test_run_schedule_disables_when_source_deleted(client, org, framework_ready):
    org_id, headers = org
    audit_id = _completed_audit(client, org, framework_ready)
    client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/schedule",
        headers=headers, json={"cadence": "weekly"},
    )

    with SessionLocal() as db:
        schedule = db.scalar(
            select(AuditSchedule).where(AuditSchedule.source_audit_id == uuid.UUID(audit_id))
        )
        schedule_id = schedule.id
        source = db.get(Audit, uuid.UUID(audit_id))
        db.delete(source)
        db.commit()

    with SessionLocal() as db:
        schedule = db.get(AuditSchedule, schedule_id)
        assert schedule.source_audit_id is None  # ON DELETE SET NULL

        result = run_schedule(db, schedule)
        db.commit()

        assert result is None
        db.refresh(schedule)
        assert schedule.is_active is False

        notif = db.scalar(
            select(Notification).where(
                Notification.organization_id == uuid.UUID(org_id),
                Notification.kind == "audit_schedule.disabled",
            )
        )
        assert notif is not None


def test_run_due_schedules_only_processes_due_ones(client, org, framework_ready):
    org_id, headers = org
    audit_id = _completed_audit(client, org, framework_ready)
    client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/schedule",
        headers=headers, json={"cadence": "weekly"},
    )

    with SessionLocal() as db:
        due = db.scalar(
            select(AuditSchedule).where(AuditSchedule.source_audit_id == uuid.UUID(audit_id))
        )
        due.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)

        not_due = AuditSchedule(
            organization_id=uuid.UUID(org_id), source_audit_id=uuid.UUID(audit_id),
            title_template="Autre planification", framework=FrameworkCode.RGPD,
            cadence=ScheduleCadence.MONTHLY,
            next_run_at=datetime.now(timezone.utc) + timedelta(days=10),
        )
        db.add(not_due)
        db.commit()
        not_due_id = not_due.id
        due_id = due.id

        run_due_schedules(db)
        db.commit()

    with SessionLocal() as db:
        assert db.get(AuditSchedule, due_id).last_run_audit_id is not None
        assert db.get(AuditSchedule, not_due_id).last_run_audit_id is None
