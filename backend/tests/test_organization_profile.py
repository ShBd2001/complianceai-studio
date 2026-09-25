"""Profil de l'organisation pour le filtre d'eligibilite (Tache 8).

PATCH /orgs/{org_id}/profile, et son effet bout-en-bout sur l'article 30 du
RGPD (dispense de registre, art. 30(5)) via le filtre d'eligibilite.
"""

import uuid
from datetime import date

import pytest
from conftest import verify_email
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.base import IngestionResult, RawRequirement
from app.ingestion.runner import ingest
from app.main import app
from app.models.enums import Pillar, RequirementKind
from app.models.organization import Organization

PWD = "Compliance!2026x"


class FakeConnector:
    code = "rgpd"

    def fetch(self) -> IngestionResult:
        articles = [
            ("Article 30", "Registre des activites de traitement",
             ("Chaque responsable du traitement tient un registre des activites "
             "de traitement effectuees sous sa responsabilite.")),
            ("Article 32", "Securite du traitement",
             ("Le responsable du traitement met en oeuvre les mesures techniques "
             "et organisationnelles appropriees.")),
        ]
        requirements = [
            RawRequirement(
                reference=ref, title=title, body=body,
                kind=RequirementKind.ARTICLE, ordering=i + 1,
                source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            )
            for i, (ref, title, body) in enumerate(articles)
        ]
        return IngestionResult(
            code="rgpd", name="RGPD (jeu de test profil)", pillar=Pillar.PRIVACY,
            authority="Parlement europeen et Conseil",
            source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            license="Decision 2011/833/UE", celex_id="32016R0679",
            version_label="profil-2026", effective_date=date(2018, 5, 25),
            requirements=requirements,
            raw_text="\n".join(f"{r.reference} {r.title} {r.body}" for r in requirements),
        )


POLICY = "Politique de securite — Acme SAS\n\nLes donnees sont chiffrees.\n"


@pytest.fixture(scope="module")
def framework_ready():
    with SessionLocal() as db:
        report = ingest(db, FakeConnector(), force=True)
        db.commit()
        assert report.status in {"created", "updated"}
        yield report


@pytest.fixture
def client():
    return TestClient(app)


def _email() -> str:
    return f"profil-{uuid.uuid4().hex[:10]}@exemple.fr"


def _register(client, email: str, org: str = "Acme SAS", plan: str | None = None) -> dict:
    payload = {
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": org, "accept_terms": True,
    }
    if plan is not None:
        payload["plan"] = plan
    r = client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201, r.text
    verify_email(client, email)
    return r.json()


def _login(client, email: str) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PWD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def org(client):
    email = _email()
    body = _register(client, email, plan="pro")  # quota d'utilisateurs > 1, voir test_viewer_cannot_modify_profile
    org_id = body["memberships"][0]["organization_id"]
    token = _login(client, email)
    return org_id, _auth(token)


# --------------------------------------------------------------------------
# Route : permissions et semantique exclude_unset
# --------------------------------------------------------------------------
def test_viewer_cannot_modify_profile(client, org):
    org_id, headers_owner = org
    viewer_email = _email()
    _register(client, viewer_email, "Autre org (compte du viewer)")
    r = client.post(
        f"/api/v1/orgs/{org_id}/members",
        json={"email": viewer_email, "role": "viewer"},
        headers=headers_owner,
    )
    assert r.status_code == 201, r.text

    token_viewer = _login(client, viewer_email)
    r = client.patch(
        f"/api/v1/orgs/{org_id}/profile",
        json={"organisme_public": True},
        headers=_auth(token_viewer),
    )
    assert r.status_code == 403


def test_admin_can_modify_profile(client, org):
    org_id, headers = org

    r = client.patch(f"/api/v1/orgs/{org_id}/profile",
                      json={"organisme_public": True, "grande_echelle": False},
                      headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["organisme_public"] is True
    assert r.json()["grande_echelle"] is False
    assert r.json()["donnees_sensibles"] is None  # jamais touche

    # Un champ omis reste inchange ; un champ envoye a null repasse a inconnu.
    r = client.patch(f"/api/v1/orgs/{org_id}/profile",
                      json={"organisme_public": None},
                      headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["organisme_public"] is None
    assert r.json()["grande_echelle"] is False  # inchange par le patch precedent


def test_headcount_modifiable_via_profile(client, org):
    """L'effectif est deja une colonne d'Organization (utilisee par
    OrganizationCreate et par l'article 30 du filtre d'eligibilite), mais
    jusqu'ici aucune route ne permettait de le modifier apres la creation."""
    org_id, headers = org

    r = client.patch(f"/api/v1/orgs/{org_id}/profile", json={"headcount": 12}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["headcount"] == 12

    r = client.patch(f"/api/v1/orgs/{org_id}/profile", json={"headcount": None}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["headcount"] is None


def test_headcount_hors_bornes_rejete(client, org):
    org_id, headers = org
    r = client.patch(f"/api/v1/orgs/{org_id}/profile", json={"headcount": 0}, headers=headers)
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Effet bout-en-bout sur le filtre d'eligibilite (article 30)
# --------------------------------------------------------------------------
def _lancer_audit(client, org_id, headers, framework_ready) -> list[dict]:
    r = client.post(f"/api/v1/orgs/{org_id}/audits", headers=headers,
                    json={"title": "Audit profil", "framework": "rgpd"})
    assert r.status_code == 201, r.text
    audit_id = r.json()["id"]
    r = client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/documents", headers=headers,
        files={"file": ("politique.txt", POLICY.encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 201, r.text
    r = client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/run", headers=headers)
    assert r.status_code == 200, r.text
    r = client.get(f"/api/v1/orgs/{org_id}/audits/{audit_id}/findings", headers=headers)
    assert r.status_code == 200
    return r.json()


def test_profil_complet_petite_structure_exempte_article_30(client, org, framework_ready):
    org_id, headers = org
    with SessionLocal() as db:
        organisation = db.scalar(select(Organization).where(Organization.id == uuid.UUID(org_id)))
        organisation.headcount = 12
        db.commit()

    r = client.patch(
        f"/api/v1/orgs/{org_id}/profile",
        json={
            "donnees_sensibles": False,
            "risque_droits_libertes": False,
            "traitement_occasionnel": True,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text

    findings = _lancer_audit(client, org_id, headers, framework_ready)
    art30 = next(f for f in findings if f["article_ref"] == "Article 30")
    assert art30["status"] == "not_applicable"
    assert art30["verdict"] == "non_applicable"
    # La justification doit citer le fondement, pas seulement affirmer
    # l'exclusion (voir eligibilite.py::_rgpd_art30, reference="RGPD art. 30(5)").
    assert "art. 30(5)" in art30["description"]


def test_profil_inconnu_laisse_article_30_suivre_le_parcours_normal(client, org, framework_ready):
    org_id, headers = org
    # Aucun profil renseigne : le filtre d'eligibilite doit repondre
    # A_VERIFIER, pas EXEMPTE -- l'article suit l'evaluation normale.
    findings = _lancer_audit(client, org_id, headers, framework_ready)
    art30 = next(f for f in findings if f["article_ref"] == "Article 30")
    assert art30["status"] != "not_applicable"
