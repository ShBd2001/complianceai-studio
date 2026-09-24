"""Comparaison de deux campagnes d'audit (Tache 9)."""

import uuid

import pytest
from conftest import verify_email
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.audit import Audit, Finding
from app.models.enums import AuditStatus, FindingStatus, Framework, Severity
from app.services import comparison

PWD = "Compliance!2026x"


def _finding(audit_id, article_ref, severity, status=FindingStatus.OPEN) -> Finding:
    return Finding(
        audit_id=audit_id, article_ref=article_ref,
        title=f"{article_ref} — Intitule", description="Constat de test.",
        severity=severity, status=status,
    )


# --------------------------------------------------------------------------
# comparison.compare() : les cinq categories
# --------------------------------------------------------------------------
def test_compare_produit_les_cinq_categories():
    with SessionLocal() as db:
        from app.models.organization import Organization

        org = Organization(name="Compare SAS", slug=f"compare-{uuid.uuid4().hex[:8]}")
        db.add(org)
        db.flush()

        avant = Audit(
            organization_id=org.id, title="Avant", framework=Framework.RGPD,
            status=AuditStatus.COMPLETED, compliance_score=60.0,
        )
        apres = Audit(
            organization_id=org.id, title="Apres", framework=Framework.RGPD,
            status=AuditStatus.COMPLETED, compliance_score=75.0,
        )
        db.add_all([avant, apres])
        db.flush()

        db.add_all([
            _finding(avant.id, "Article 5", Severity.MAJOR),      # resolu (absent apres)
            _finding(apres.id, "Article 6", Severity.CRITICAL),   # nouveau (absent avant)
            _finding(avant.id, "Article 7", Severity.MINOR),
            _finding(apres.id, "Article 7", Severity.MINOR),      # inchange
            _finding(avant.id, "Article 8", Severity.MINOR),
            _finding(apres.id, "Article 8", Severity.MAJOR),      # aggrave
            _finding(avant.id, "Article 9", Severity.MAJOR),
            _finding(apres.id, "Article 9", Severity.MINOR),      # ameliore
            # Hors perimetre des deux cotes : ne doit apparaitre nulle part.
            _finding(avant.id, "Article 99", Severity.INFO, status=FindingStatus.NOT_APPLICABLE),
            _finding(apres.id, "Article 99", Severity.INFO, status=FindingStatus.NOT_APPLICABLE),
        ])
        db.flush()

        score_delta, articles = comparison.compare(db, avant, apres)
        db.rollback()

    assert score_delta == pytest.approx(15.0)
    par_article = {a.article_ref: a for a in articles}
    assert "Article 99" not in par_article

    assert par_article["Article 5"].category == "resolu"
    assert par_article["Article 5"].severity_after is None
    assert par_article["Article 6"].category == "nouveau"
    assert par_article["Article 6"].severity_before is None
    assert par_article["Article 7"].category == "inchange"
    assert par_article["Article 8"].category == "aggrave"
    assert par_article["Article 9"].category == "ameliore"


# --------------------------------------------------------------------------
# Route : refus entre organisations differentes, referentiels differents
# --------------------------------------------------------------------------
@pytest.fixture
def client():
    return TestClient(app)


def _email() -> str:
    return f"cmp-{uuid.uuid4().hex[:10]}@exemple.fr"


def _register(client, email: str, org: str = "Acme SAS") -> dict:
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": org, "accept_terms": True,
    })
    assert r.status_code == 201, r.text
    verify_email(client, email)
    return r.json()


def _login(client, email: str) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PWD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_refuse_la_comparaison_entre_deux_organisations(client):
    email_a, email_b = _email(), _email()
    body_a = _register(client, email_a, "Org A")
    body_b = _register(client, email_b, "Org B")
    org_a_id = body_a["memberships"][0]["organization_id"]
    org_b_id = body_b["memberships"][0]["organization_id"]
    token_a = _login(client, email_a)
    token_b = _login(client, email_b)

    r = client.post(f"/api/v1/orgs/{org_a_id}/audits", headers=_auth(token_a),
                    json={"title": "Audit A", "framework": "rgpd"})
    assert r.status_code == 201, r.text
    audit_a_id = r.json()["id"]

    r = client.post(f"/api/v1/orgs/{org_b_id}/audits", headers=_auth(token_b),
                    json={"title": "Audit B", "framework": "rgpd"})
    assert r.status_code == 201, r.text
    audit_b_id = r.json()["id"]

    # org A tente de comparer sa campagne a celle de l'organisation B :
    # _get_audit(with_) ne la trouve pas dans le perimetre de A -> 404.
    r = client.get(
        f"/api/v1/orgs/{org_a_id}/audits/{audit_a_id}/compare",
        params={"with": audit_b_id}, headers=_auth(token_a),
    )
    assert r.status_code == 404


def test_refuse_la_comparaison_entre_deux_referentiels(client):
    email = _email()
    body = _register(client, email)
    org_id = body["memberships"][0]["organization_id"]
    token = _login(client, email)
    headers = _auth(token)

    r = client.post(f"/api/v1/orgs/{org_id}/audits", headers=headers,
                    json={"title": "Audit RGPD", "framework": "rgpd"})
    assert r.status_code == 201, r.text
    audit_rgpd_id = r.json()["id"]

    r = client.post(f"/api/v1/orgs/{org_id}/audits", headers=headers,
                    json={"title": "Audit NIS2", "framework": "nis2"})
    assert r.status_code == 201, r.text
    audit_nis2_id = r.json()["id"]

    r = client.get(
        f"/api/v1/orgs/{org_id}/audits/{audit_rgpd_id}/compare",
        params={"with": audit_nis2_id}, headers=headers,
    )
    assert r.status_code == 409
