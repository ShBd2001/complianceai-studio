"""Vérification de citation et revue humaine (Tâche 2).

Deux niveaux de test : la regle pure `_verification_humaine`, exhaustive sur
la table de la specification ; puis la chaine complete (API), qui verifie que
ces champs sont bien ecrits sur les constats persistes.
"""

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
from app.services import audit_engine

PWD = "Compliance!2026x"


# --------------------------------------------------------------------------
# _verification_humaine : regle pure
# --------------------------------------------------------------------------
def test_exclusion_filtre_eligibilite_ne_necessite_aucune_revue():
    verdict = {"_source": audit_engine.SOURCE_ELIGIBILITY, "conforme": "non_applicable"}
    citation_verified, needs_review, reason = audit_engine._verification_humaine(
        verdict, "non_applicable"
    )
    assert citation_verified is None
    assert needs_review is False
    assert reason is None


def test_non_applicable_par_heuristique_est_a_revoir():
    verdict = {"_source": audit_engine.SOURCE_HEURISTIC, "conforme": "non_applicable"}
    citation_verified, needs_review, _ = audit_engine._verification_humaine(
        verdict, "non_applicable"
    )
    assert citation_verified is None
    assert needs_review is True


def test_non_applicable_par_propagation_llm_ne_necessite_pas_de_revue():
    """Non applicable par dependance a un article ecarte (_propagate_dependencies) :
    source LLM, pas heuristique -> pas de revue automatique."""
    verdict = {"_source": audit_engine.SOURCE_LLM, "conforme": "non_applicable"}
    _, needs_review, _ = audit_engine._verification_humaine(verdict, "non_applicable")
    assert needs_review is False


def test_citation_llm_verifiee_ne_declenche_pas_de_revue():
    verdict = {
        "_source": audit_engine.SOURCE_LLM, "preuve": "texte cite",
        "_passage_verifie": object(), "confiance": 0.9,
    }
    citation_verified, needs_review, reason = audit_engine._verification_humaine(
        verdict, "non"
    )
    assert citation_verified is True
    assert needs_review is False
    assert reason is None


def test_citation_llm_introuvable_declenche_revue_avec_motif():
    verdict = {
        "_source": audit_engine.SOURCE_LLM, "preuve": "texte cite",
        "_passage_verifie": None, "confiance": 0.9,
    }
    citation_verified, needs_review, reason = audit_engine._verification_humaine(
        verdict, "indetermine"
    )
    assert citation_verified is False
    assert needs_review is True
    assert "introuvable" in reason
    assert "Les extraits ne permettent pas de conclure" in reason


def test_confiance_faible_seule_declenche_la_revue():
    verdict = {"_source": audit_engine.SOURCE_LLM, "preuve": None, "confiance": 0.2}
    citation_verified, needs_review, reason = audit_engine._verification_humaine(
        verdict, "non"
    )
    assert citation_verified is None  # pas de citation fournie : rien a verifier
    assert needs_review is True
    assert reason == "Confiance du modele faible"


def test_confiance_suffisante_sans_autre_motif_ne_declenche_rien():
    verdict = {"_source": audit_engine.SOURCE_LLM, "preuve": None, "confiance": 0.8}
    citation_verified, needs_review, reason = audit_engine._verification_humaine(
        verdict, "non"
    )
    assert citation_verified is None
    assert needs_review is False
    assert reason is None


# --------------------------------------------------------------------------
# Chaine complete : les champs sont bien persistes sur le Finding
# --------------------------------------------------------------------------
class FakeConnector:
    code = "rgpd"

    def fetch(self) -> IngestionResult:
        articles = [
            ("Article 32", "Sécurité du traitement",
             ("Le responsable du traitement met en oeuvre les mesures techniques et "
              "organisationnelles appropriees, notamment le chiffrement des donnees.")),
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
            code="rgpd", name="RGPD (jeu de test verification)", pillar=Pillar.PRIVACY,
            authority="Parlement europeen et Conseil",
            source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            license="Decision 2011/833/UE", celex_id="32016R0679",
            version_label="verif-2026", effective_date=date(2018, 5, 25),
            requirements=requirements,
            raw_text="\n".join(f"{r.reference} {r.title} {r.body}" for r in requirements),
        )


POLICY = """Politique de securite — Acme SAS

Les donnees sont chiffrees au repos et en transit. Les acces sont restreints
par authentification forte.
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
    email = f"verif-{uuid.uuid4().hex[:8]}@exemple.fr"
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
                    json={"title": "Audit verification", "framework": "rgpd"})
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


def test_sans_modele_toutes_les_exigences_evaluees_sont_a_revoir(client, org, framework_ready):
    """Les tests tournent sans cle LLM (conftest) : chaque constat provient de
    l'heuristique et doit etre signale a la revue humaine."""
    findings = _lancer_audit(client, org, framework_ready)
    assert findings
    for finding in findings:
        assert finding["needs_human_review"] is True
        assert finding["review_reason"]


def test_citation_fabriquee_ramene_a_indetermine_et_signale_la_revue(monkeypatch, client, org, framework_ready):
    from app.services import llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {
        "conforme": "oui", "severite": "info", "confiance": 0.9,
        "constat": "Chiffrement en place.",
        "preuve": "Une citation entierement inventee, absente du document.",
        "recommandation": None,
    })

    findings = _lancer_audit(client, org, framework_ready)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["verdict"] == "indetermine"
    assert finding["citation_verified"] is False
    assert finding["needs_human_review"] is True
    assert finding["review_reason"]


def test_citation_reelle_sur_verdict_non_est_verifiee(monkeypatch, client, org, framework_ready):
    from app.services import llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {
        "conforme": "non", "severite": "major", "confiance": 0.8,
        "constat": "Mesures insuffisantes.",
        "preuve": "Les donnees sont chiffrees au repos et en transit.",
        "recommandation": "Completer la politique.",
    })

    findings = _lancer_audit(client, org, framework_ready)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["verdict"] == "non"
    assert finding["citation_verified"] is True
