"""Metriques d'execution d'une campagne : appels, jetons, mode degrade (Tache 3)."""

import uuid
from datetime import date

import pytest
from conftest import verify_email
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.ingestion.base import IngestionResult, RawRequirement
from app.ingestion.runner import ingest
from app.main import app
from app.models.enums import Pillar, RequirementKind

PWD = "Compliance!2026x"

ARTICLES = [
    ("Article 30", "Registre des activites de traitement",
     "Chaque responsable du traitement tient un registre des activites."),
    ("Article 32", "Securite du traitement",
     "Les donnees a caractere personnel doivent etre protegees."),
    ("Article 33", "Notification des violations",
     "En cas de violation, l'autorite de controle est notifiee sous 72 heures."),
    ("Article 35", "Analyse d'impact",
     "Une analyse d'impact est realisee pour les traitements a risque eleve."),
    ("Article 5", "Principes relatifs au traitement",
     "Les donnees sont traitees de maniere licite, loyale et transparente."),
]


class FakeConnector:
    code = "rgpd"

    def fetch(self) -> IngestionResult:
        requirements = [
            RawRequirement(
                reference=ref, title=title, body=body,
                kind=RequirementKind.ARTICLE, ordering=i + 1,
                source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            )
            for i, (ref, title, body) in enumerate(ARTICLES)
        ]
        return IngestionResult(
            code="rgpd", name="RGPD (jeu de test metriques)", pillar=Pillar.PRIVACY,
            authority="Parlement europeen et Conseil",
            source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            license="Decision 2011/833/UE", celex_id="32016R0679",
            version_label="metriques-2026", effective_date=date(2018, 5, 25),
            requirements=requirements,
            raw_text="\n".join(f"{r.reference} {r.title} {r.body}" for r in requirements),
        )


POLICY = """Politique de securite — Acme SAS

Un registre des activites de traitement est tenu a jour. Les donnees sont
chiffrees au repos et en transit. En cas de violation, l'autorite de
controle est notifiee dans les meilleurs delais.
"""


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


@pytest.fixture
def org(client):
    email = f"metrics-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": "Acme SAS", "accept_terms": True,
    })
    assert r.status_code == 201, r.text
    org_id = r.json()["memberships"][0]["organization_id"]
    verify_email(client, email)
    token = client.post("/api/v1/auth/login",
                        json={"email": email, "password": PWD}).json()["access_token"]
    return org_id, {"Authorization": f"Bearer {token}"}


def _lancer_audit(client, org, framework_ready):
    org_id, headers = org
    r = client.post(f"/api/v1/orgs/{org_id}/audits", headers=headers,
                    json={"title": "Audit metriques", "framework": "rgpd"})
    assert r.status_code == 201, r.text
    audit_id = r.json()["id"]
    r = client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/documents", headers=headers,
        files={"file": ("politique.txt", POLICY.encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 201, r.text
    r = client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/run", headers=headers)
    assert r.status_code == 200, r.text
    r = client.get(f"/api/v1/orgs/{org_id}/audits/{audit_id}", headers=headers)
    assert r.status_code == 200
    return r.json()


def test_compteurs_corrects_avec_un_modele_toujours_disponible(monkeypatch, client, org, framework_ready):
    from app.services import llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {
        "conforme": "oui", "severite": "info", "confiance": 0.9,
        "constat": "Conforme.", "preuve": None, "recommandation": None,
        "_usage": {"prompt_tokens": 100, "completion_tokens": 20},
    })

    audit = _lancer_audit(client, org, framework_ready)

    assert audit["degraded"] is False
    assert audit["llm_calls"] == 5
    assert audit["llm_prompt_tokens"] == 500
    assert audit["llm_completion_tokens"] == 100
    assert audit["llm_model"]
    assert audit["retriever"]
    assert audit["duration_seconds"] is not None and audit["duration_seconds"] >= 0


def test_mode_degrade_quand_le_modele_echoue_trop_souvent(monkeypatch, client, org, framework_ready):
    """Plus de 30 % de repli heuristique (DEGRADED_THRESHOLD) : le score
    n'est pas publie et degraded=True.

    Echoue systematiquement plutot que sur un compteur precis : le
    disjoncteur (LLM_BREAKER_THRESHOLD) ouvre le circuit apres quelques
    echecs consecutifs et route alors le reste directement vers
    l'heuristique sans meme appeler complete_json -- un decompte exact des
    appels a l'echec serait fragile et dependant de l'ordre d'execution des
    workers paralleles."""
    from app.services import llm

    monkeypatch.setattr(llm, "is_available", lambda: True)

    def echoue_toujours(*args, **kwargs):
        raise RuntimeError("Panne simulee du fournisseur.")

    monkeypatch.setattr(llm, "complete_json", echoue_toujours)

    audit = _lancer_audit(client, org, framework_ready)

    assert audit["degraded"] is True
    assert audit["compliance_score"] is None
    assert audit["llm_fallbacks"] == 5
    assert audit["llm_calls"] == 0
