"""Tests de la retention personnalisee des documents (offre Cabinet).

Verifie deux choses independantes : le controle d'acces API (offre Cabinet
uniquement, owner uniquement, plancher de RETENTION_MIN_JOURS jours) et la
logique de purge elle-meme (app/services/retention.py) -- en particulier
qu'un document purge perd son fichier et ses fragments indexes, mais que le
constat (Finding) et le rapport (Report) deja produits survivent, comme
documente dans DA-04 (docs/architecture.md) : la valeur probante de l'audit
ne doit pas dependre de la duree de vie du document source.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.main import app
from app.models.audit import Audit, Document, DocumentChunk, Finding, Report
from app.models.enums import AuditStatus, Framework, FindingStatus, OrgPlan, Severity
from app.models.organization import Organization
from app.services.audit_engine import index_document
from app.services.documents import storage_root
from app.services.retention import RETENTION_MIN_JOURS, purge_expired_documents
from conftest import verify_email

PWD = "Compliance!2026x"


def _email() -> str:
    return f"retention-{uuid.uuid4().hex[:10]}@exemple.fr"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient, email: str, org: str, plan: str) -> dict:
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": org, "accept_terms": True, "plan": plan,
    })
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
# API : reservee a l'offre Cabinet, a l'owner, plancher de 30 jours
# --------------------------------------------------------------------------
def test_retention_refusee_hors_offre_cabinet(client):
    email = _email()
    owner = _register(client, email, "Beta SAS", plan="pro")
    org_id = owner["memberships"][0]["organization_id"]
    token = _login(client, email)

    r = client.patch(
        f"/api/v1/orgs/{org_id}/retention",
        json={"document_retention_days": 60},
        headers=_auth(token),
    )
    assert r.status_code == 403


def test_retention_refuse_sous_le_plancher(client):
    email = _email()
    owner = _register(client, email, "Cabinet Gamma", plan="cabinet")
    org_id = owner["memberships"][0]["organization_id"]
    token = _login(client, email)

    r = client.patch(
        f"/api/v1/orgs/{org_id}/retention",
        json={"document_retention_days": RETENTION_MIN_JOURS - 1},
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_retention_configurable_par_owner_cabinet(client):
    email = _email()
    owner = _register(client, email, "Cabinet Delta", plan="cabinet")
    org_id = owner["memberships"][0]["organization_id"]
    token = _login(client, email)

    r = client.patch(
        f"/api/v1/orgs/{org_id}/retention",
        json={"document_retention_days": 90},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["document_retention_days"] == 90

    r = client.get(f"/api/v1/orgs/{org_id}", headers=_auth(token))
    assert r.json()["document_retention_days"] == 90

    # Repasser a null desactive la purge automatique -- doit rester permis.
    r = client.patch(
        f"/api/v1/orgs/{org_id}/retention",
        json={"document_retention_days": None},
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["document_retention_days"] is None


def test_retention_reservee_a_owner(client):
    owner_email, admin_email = _email(), _email()
    owner = _register(client, owner_email, "Cabinet Epsilon", plan="cabinet")
    org_id = owner["memberships"][0]["organization_id"]
    owner_token = _login(client, owner_email)

    _register(client, admin_email, "Autre SAS", plan="essentiel")
    r = client.post(
        f"/api/v1/orgs/{org_id}/members",
        json={"email": admin_email, "role": "admin"},
        headers=_auth(owner_token),
    )
    assert r.status_code == 201
    admin_token = _login(client, admin_email)

    r = client.patch(
        f"/api/v1/orgs/{org_id}/retention",
        json={"document_retention_days": 60},
        headers=_auth(admin_token),
    )
    assert r.status_code == 403  # un admin n'est pas un owner


# --------------------------------------------------------------------------
# Purge : le fichier et les fragments disparaissent, pas les constats/rapport
# --------------------------------------------------------------------------
def test_purge_respecte_retention_et_preserve_findings_et_rapport():
    with SessionLocal() as db:
        org = Organization(
            name="Cabinet Zeta",
            slug=f"cabinet-zeta-{uuid.uuid4().hex[:8]}",
            country="FR",
            plan=OrgPlan.CABINET,
            document_retention_days=RETENTION_MIN_JOURS,
        )
        db.add(org)
        db.flush()

        audit = Audit(
            organization_id=org.id, title="Audit test retention",
            framework=Framework.RGPD, status=AuditStatus.COMPLETED,
        )
        db.add(audit)
        db.flush()

        cle_ancien = f"{org.id}/ancien-retention-test.txt"
        (storage_root() / cle_ancien).parent.mkdir(parents=True, exist_ok=True)
        (storage_root() / cle_ancien).write_bytes(b"contenu ancien")
        ancien = Document(
            audit_id=audit.id, organization_id=org.id, filename="ancien.txt",
            mime_type="text/plain", size_bytes=15, sha256="0" * 64,
            storage_key=cle_ancien,
        )
        ancien.created_at = datetime.now(timezone.utc) - timedelta(days=RETENTION_MIN_JOURS + 5)
        db.add(ancien)
        db.flush()

        cle_recent = f"{org.id}/recent-retention-test.txt"
        (storage_root() / cle_recent).write_bytes(b"contenu recent")
        recent = Document(
            audit_id=audit.id, organization_id=org.id, filename="recent.txt",
            mime_type="text/plain", size_bytes=14, sha256="1" * 64,
            storage_key=cle_recent,
        )
        db.add(recent)
        db.flush()

        db.add(DocumentChunk(
            document_id=ancien.id, organization_id=org.id, chunk_index=0,
            content="fragment indexe", meta={},
        ))

        finding = Finding(
            audit_id=audit.id, article_ref="Article 30", title="Constat de test",
            description="Registre absent.", severity=Severity.MINOR,
            status=FindingStatus.OPEN, source_document_id=ancien.id,
        )
        db.add(finding)

        report = Report(
            audit_id=audit.id, version=1, storage_key=f"{org.id}/rapport-retention-test.pdf",
            sha256="2" * 64, summary={},
        )
        db.add(report)
        db.flush()

        finding_id, report_id, ancien_id, recent_id = finding.id, report.id, ancien.id, recent.id

        purges = purge_expired_documents(db)
        db.commit()

    assert purges == 1

    with SessionLocal() as db:
        ancien_relu = db.get(Document, ancien_id)
        recent_relu = db.get(Document, recent_id)
        assert ancien_relu.content_purged_at is not None
        assert recent_relu.content_purged_at is None

        assert not (storage_root() / cle_ancien).exists()
        assert (storage_root() / cle_recent).exists()

        chunks_restants = db.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == ancien_id)
        ).all()
        assert chunks_restants == []

        # La valeur probante de l'audit survit a la purge du document source.
        assert db.get(Finding, finding_id) is not None
        assert db.get(Report, report_id) is not None

    (storage_root() / cle_recent).unlink(missing_ok=True)


def test_purge_ignore_organisation_sans_retention_configuree():
    with SessionLocal() as db:
        org = Organization(
            name="Cabinet Eta", slug=f"cabinet-eta-{uuid.uuid4().hex[:8]}",
            country="FR", plan=OrgPlan.CABINET, document_retention_days=None,
        )
        db.add(org)
        db.flush()

        audit = Audit(
            organization_id=org.id, title="Audit sans retention",
            framework=Framework.RGPD, status=AuditStatus.COMPLETED,
        )
        db.add(audit)
        db.flush()

        cle = f"{org.id}/jamais-purge.txt"
        (storage_root() / cle).parent.mkdir(parents=True, exist_ok=True)
        (storage_root() / cle).write_bytes(b"contenu")
        document = Document(
            audit_id=audit.id, organization_id=org.id, filename="vieux.txt",
            mime_type="text/plain", size_bytes=7, sha256="3" * 64, storage_key=cle,
        )
        document.created_at = datetime.now(timezone.utc) - timedelta(days=3650)
        db.add(document)
        db.flush()
        document_id = document.id

        purge_expired_documents(db)
        db.commit()

    with SessionLocal() as db:
        relu = db.get(Document, document_id)
        assert relu.content_purged_at is None
        assert (storage_root() / cle).exists()

    (storage_root() / cle).unlink(missing_ok=True)


# --------------------------------------------------------------------------
# run_audit relit le fichier a chaque execution (pas seulement au depot) :
# un document purge ne doit pas faire planter une reanalyse.
# --------------------------------------------------------------------------
def test_index_document_sur_document_purge_ne_plante_pas():
    with SessionLocal() as db:
        org = Organization(
            name="Cabinet Theta", slug=f"cabinet-theta-{uuid.uuid4().hex[:8]}",
            country="FR", plan=OrgPlan.CABINET, document_retention_days=RETENTION_MIN_JOURS,
        )
        db.add(org)
        db.flush()

        audit = Audit(
            organization_id=org.id, title="Audit reanalyse", framework=Framework.RGPD,
            status=AuditStatus.COMPLETED,
        )
        db.add(audit)
        db.flush()

        document = Document(
            audit_id=audit.id, organization_id=org.id, filename="purge.txt",
            mime_type="text/plain", size_bytes=1, sha256="4" * 64,
            # Cle pointant vers un fichier qui n'existe pas : simule le fichier
            # deja efface par la purge, sans dependre de l'ordre d'execution
            # des autres tests.
            storage_key=f"{org.id}/fichier-inexistant.txt",
            content_purged_at=datetime.now(timezone.utc),
        )
        db.add(document)
        db.flush()

        # Sans le garde-fou, read_document() leve FileNotFoundError ici.
        fragments = index_document(db, document)
        assert fragments == 0

