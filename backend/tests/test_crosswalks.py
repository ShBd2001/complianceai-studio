"""Tests des correspondances entre referentiels (crosswalk).

Le point critique, releve en revue de conception : une correspondance dont un
cote a ete supersede par une reingestion (nouvelle FrameworkVersion) ne doit
plus apparaitre, sans quoi elle induirait en erreur silencieusement plutot
que de simplement disparaitre le temps que le seed soit rejoue.
"""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.base import IngestionResult, RawRequirement
from app.ingestion.runner import ingest
from app.main import app
from app.models.enums import Pillar, RequirementKind
from app.models.framework import Crosswalk, FrameworkVersion, Requirement
from conftest import verify_email

PWD = "Compliance!2026x"


class FakeRgpdConnector:
    """Deux articles, pour croiser une correspondance entre deux exigences
    distinctes plutot qu'un article rattache a lui-meme."""

    code = "rgpd"

    def __init__(self, body_suffix: str = "") -> None:
        self.body_suffix = body_suffix

    def fetch(self) -> IngestionResult:
        reqs = [
            RawRequirement(
                reference="Article 32", title="Securite du traitement",
                body="Mesures de securite techniques." + self.body_suffix,
                kind=RequirementKind.ARTICLE, ordering=1,
                source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            ),
            RawRequirement(
                reference="Article 33", title="Notification des violations",
                body="Notification a l'autorite de controle." + self.body_suffix,
                kind=RequirementKind.ARTICLE, ordering=2,
                source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            ),
        ]
        return IngestionResult(
            code="rgpd", name="Reglement general sur la protection des donnees",
            pillar=Pillar.PRIVACY, authority="Parlement europeen et Conseil",
            source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            license="Decision 2011/833/UE", celex_id="32016R0679",
            version_label="2016/679", effective_date=date(2018, 5, 25),
            requirements=reqs,
            raw_text="\n".join(f"{r.reference} {r.body}" for r in reqs),
        )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def org(client: TestClient):
    email = f"cw-{uuid.uuid4().hex[:8]}@exemple.fr"
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


def _current_requirement(db, reference: str) -> Requirement:
    return db.scalar(
        select(Requirement)
        .join(FrameworkVersion, Requirement.version_id == FrameworkVersion.id)
        .where(FrameworkVersion.is_current.is_(True), Requirement.reference == reference)
    )


def test_crosswalk_hides_pair_pointing_to_superseded_requirement(client, org):
    with SessionLocal() as db:
        ingest(db, FakeRgpdConnector(), force=True)
        db.commit()
        old_32 = _current_requirement(db, "Article 32")
        old_32_id = old_32.id

        # Reingestion : nouvelle version courante, l'ancienne devient perimee
        # mais ses lignes Requirement restent en base (jamais supprimees).
        ingest(db, FakeRgpdConnector(body_suffix=" Modification."), force=True)
        db.commit()
        new_32 = _current_requirement(db, "Article 32")
        new_33 = _current_requirement(db, "Article 33")
        assert new_32.id != old_32_id

        db.add_all([
            Crosswalk(
                source_requirement_id=old_32_id, target_requirement_id=new_33.id,
                coverage=0.5, rationale="Correspondance perimee (source non courante).",
            ),
            Crosswalk(
                source_requirement_id=new_32.id, target_requirement_id=new_33.id,
                coverage=0.9, rationale="Correspondance courante.",
            ),
        ])
        db.commit()

    _, headers = org
    r = client.get("/api/v1/frameworks/rgpd/crosswalks", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["rationale"] == "Correspondance courante."
    assert body[0]["source_reference"] == "Article 32"
    assert body[0]["target_reference"] == "Article 33"


def test_crosswalk_unknown_framework_gives_404(client, org):
    _, headers = org
    r = client.get("/api/v1/frameworks/referentiel-inexistant/crosswalks", headers=headers)
    assert r.status_code == 404


def test_crosswalk_empty_when_none_seeded(client, org):
    with SessionLocal() as db:
        ingest(db, FakeRgpdConnector(body_suffix=" Sans crosswalk."), force=True)
        db.commit()

    _, headers = org
    r = client.get("/api/v1/frameworks/rgpd/crosswalks", headers=headers)
    assert r.status_code == 200
    assert r.json() == []
