"""Filtre d'eligibilite NIS2, DORA, AI Act (Tache F1).

Deux niveaux : la regle pure `evaluer()`, exhaustive sur le tableau de
correspondance documente en tete de eligibilite.py ; puis un cas bout-en-bout
verifiant qu'une entite hors champ DORA n'appelle jamais le modele.
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
from app.services.eligibilite import (
    ProfilOrganisme,
    Verdict,
    evaluer,
    referentiel_hors_champ,
)

PWD = "Compliance!2026x"


# --------------------------------------------------------------------------
# NIS2
# --------------------------------------------------------------------------
def test_nis2_entite_non_concernee_exempte_les_obligations_generales():
    profil = ProfilOrganisme(entite_nis2="non_concernee")
    for article in (20, 21, 23, 24, 29, 30):
        decision = evaluer("nis2", article, profil)
        assert decision.verdict is Verdict.EXEMPTE, article
        assert "NIS2" in decision.reference


def test_nis2_entite_essentielle_rend_les_obligations_generales_applicables():
    profil = ProfilOrganisme(entite_nis2="essentielle")
    for article in (20, 21, 23, 24, 29, 30):
        assert evaluer("nis2", article, profil).verdict is Verdict.APPLICABLE, article


def test_nis2_profil_inconnu_laisse_a_verifier():
    profil = ProfilOrganisme()
    for article in (20, 21, 23, 24, 27, 28, 29, 30):
        assert evaluer("nis2", article, profil).verdict is Verdict.A_VERIFIER, article


def test_nis2_art27_28_ne_sont_pas_exemptes_par_le_seul_statut_essentiel():
    """Correction 1 : art. 27/28 visent les fournisseurs DNS et registres de
    noms de domaine, pas toute entite essentielle -- le statut seul ne suffit
    jamais a conclure a l'applicabilite."""
    profil = ProfilOrganisme(entite_nis2="essentielle")
    for article in (27, 28):
        assert evaluer("nis2", article, profil).verdict is Verdict.A_VERIFIER, article

    profil_non_concernee = ProfilOrganisme(entite_nis2="non_concernee")
    for article in (27, 28):
        assert evaluer("nis2", article, profil_non_concernee).verdict is Verdict.EXEMPTE, article


# --------------------------------------------------------------------------
# DORA
# --------------------------------------------------------------------------
def test_dora_entite_non_financiere_exempte_les_obligations_generales():
    profil = ProfilOrganisme(entite_financiere_dora=False)
    for article in (5, 6, 16, 19, 24, 28, 30):
        decision = evaluer("dora", article, profil)
        assert decision.verdict is Verdict.EXEMPTE, article
        assert "DORA" in decision.reference


def test_dora_entite_financiere_rend_applicable():
    profil = ProfilOrganisme(entite_financiere_dora=True)
    assert evaluer("dora", 5, profil).verdict is Verdict.APPLICABLE


def test_dora_art23_ne_suffit_pas_avec_seul_statut_financier():
    """Correction 2 : art. 23 ne vise que les etablissements de credit, de
    paiement et assimiles, pas toute entite financiere."""
    profil = ProfilOrganisme(entite_financiere_dora=True)
    assert evaluer("dora", 23, profil).verdict is Verdict.A_VERIFIER

    profil_non_financiere = ProfilOrganisme(entite_financiere_dora=False)
    assert evaluer("dora", 23, profil_non_financiere).verdict is Verdict.EXEMPTE


def test_dora_articles_institutionnels_toujours_exemptes():
    """Correction 3 : art. 15, 20, 21 sont des obligations des AES, jamais
    de l'entite financiere -- exemptes meme pour une entite financiere
    avouee, et meme sans aucun profil renseigne."""
    for profil in (ProfilOrganisme(), ProfilOrganisme(entite_financiere_dora=True)):
        for article in (15, 20, 21):
            assert evaluer("dora", article, profil).verdict is Verdict.EXEMPTE, (article, profil)


# --------------------------------------------------------------------------
# AI Act
# --------------------------------------------------------------------------
def test_ai_act_article5_jamais_exempte():
    profil_tout_faux = ProfilOrganisme(
        ia_fournisseur_haut_risque=False, ia_deployeur_haut_risque=False, ia_utilisee=False
    )
    assert evaluer("ai_act", 5, profil_tout_faux).verdict is Verdict.APPLICABLE
    assert evaluer("ai_act", 5, ProfilOrganisme()).verdict is Verdict.APPLICABLE


def test_ai_act_transparence_art50_suit_ia_utilisee():
    assert evaluer("ai_act", 50, ProfilOrganisme(ia_utilisee=False)).verdict is Verdict.EXEMPTE
    assert evaluer("ai_act", 50, ProfilOrganisme(ia_utilisee=True)).verdict is Verdict.APPLICABLE
    assert evaluer("ai_act", 50, ProfilOrganisme()).verdict is Verdict.A_VERIFIER


def test_ai_act_fournisseur_exempte_sans_ia_a_haut_risque_fournie():
    profil = ProfilOrganisme(ia_fournisseur_haut_risque=False)
    for article in (8, 16, 22, 25, 47, 72):
        assert evaluer("ai_act", article, profil).verdict is Verdict.EXEMPTE, article


def test_ai_act_deployeur_general_suit_ia_deployeur_haut_risque():
    assert evaluer("ai_act", 26, ProfilOrganisme(ia_deployeur_haut_risque=False)).verdict is Verdict.EXEMPTE
    assert evaluer("ai_act", 26, ProfilOrganisme(ia_deployeur_haut_risque=True)).verdict is Verdict.APPLICABLE


def test_ai_act_art27_86_ne_suffisent_pas_avec_seul_statut_deployeur():
    """Correction 4 : art. 27 (analyse d'impact) et 86 (droit a
    l'explication) ne visent qu'un sous-ensemble des deployeurs a haut
    risque -- True ne suffit pas a conclure, contrairement a l'art. 26."""
    profil = ProfilOrganisme(ia_deployeur_haut_risque=True)
    assert evaluer("ai_act", 27, profil).verdict is Verdict.A_VERIFIER
    assert evaluer("ai_act", 86, profil).verdict is Verdict.A_VERIFIER

    profil_non_deployeur = ProfilOrganisme(ia_deployeur_haut_risque=False)
    assert evaluer("ai_act", 27, profil_non_deployeur).verdict is Verdict.EXEMPTE
    assert evaluer("ai_act", 86, profil_non_deployeur).verdict is Verdict.EXEMPTE


def test_ai_act_art23_24_aucune_regle_reste_applicable():
    """Correction 5 : importateurs/distributeurs, role distinct du
    fournisseur, aucun champ de profil dedie -- reste APPLICABLE par defaut
    quel que soit le profil, y compris un fournisseur affirme."""
    profil = ProfilOrganisme(ia_fournisseur_haut_risque=False)
    assert evaluer("ai_act", 23, profil).verdict is Verdict.APPLICABLE
    assert evaluer("ai_act", 24, profil).verdict is Verdict.APPLICABLE


# --------------------------------------------------------------------------
# referentiel_hors_champ()
# --------------------------------------------------------------------------
def test_referentiel_hors_champ_dora_pour_entite_non_financiere():
    profil = ProfilOrganisme(entite_financiere_dora=False)
    assert referentiel_hors_champ("dora", profil) is True


def test_referentiel_hors_champ_faux_si_profil_incomplet():
    """Le principe de prudence s'applique aussi a l'avertissement : un
    profil non renseigne ne doit jamais le declencher (A_VERIFIER partout,
    jamais EXEMPTE partout)."""
    assert referentiel_hors_champ("dora", ProfilOrganisme()) is False


def test_referentiel_hors_champ_ai_act_jamais_vrai():
    """L'article 5 n'est jamais exempte : l'AI Act ne peut donc jamais etre
    signale entierement hors champ par ce mecanisme."""
    profil = ProfilOrganisme(
        ia_fournisseur_haut_risque=False, ia_deployeur_haut_risque=False, ia_utilisee=False
    )
    assert referentiel_hors_champ("ai_act", profil) is False


# --------------------------------------------------------------------------
# Bout-en-bout : entite non financiere, campagne DORA, zero appel modele
# --------------------------------------------------------------------------
class FakeDoraConnector:
    code = "dora"

    def fetch(self) -> IngestionResult:
        articles = [
            ("Article 5", "Gouvernance et organisation",
             "Les entites financieres disposent d'un cadre de gouvernance."),
            ("Article 23", "Incidents operationnels ou de securite lies au paiement",
             "Les exigences du present chapitre s'appliquent aux etablissements de credit."),
            ("Article 15", "Harmonisation accrue des outils",
             "Les AES elaborent des projets communs de normes techniques."),
        ]
        requirements = [
            RawRequirement(
                reference=ref, title=title, body=body,
                kind=RequirementKind.ARTICLE, ordering=i + 1,
                source_url="https://eur-lex.europa.eu/eli/reg/2022/2554/oj",
            )
            for i, (ref, title, body) in enumerate(articles)
        ]
        return IngestionResult(
            code="dora", name="DORA (jeu de test F1)", pillar=Pillar.OPERATIONAL_RESILIENCE,
            authority="Parlement europeen et Conseil",
            source_url="https://eur-lex.europa.eu/eli/reg/2022/2554/oj",
            license="Decision 2011/833/UE", celex_id="32022R2554",
            version_label="f1-2026", effective_date=date(2025, 1, 17),
            requirements=requirements,
            raw_text="\n".join(f"{r.reference} {r.title} {r.body}" for r in requirements),
        )


POLICY = "Politique de securite — Boulangerie Durand SARL\n\nAucune activite financiere.\n"


@pytest.fixture(scope="module")
def framework_ready():
    with SessionLocal() as db:
        report = ingest(db, FakeDoraConnector(), force=True)
        db.commit()
        assert report.status in {"created", "updated"}
        yield report


@pytest.fixture
def client():
    return TestClient(app)


def _email() -> str:
    return f"f1-{uuid.uuid4().hex[:10]}@exemple.fr"


def _register(client, email: str) -> dict:
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": "Boulangerie Durand SARL", "accept_terms": True,
    })
    assert r.status_code == 201, r.text
    verify_email(client, email)
    return r.json()


def _login(client, email: str) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PWD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_entite_non_financiere_campagne_dora_sans_appel_modele(monkeypatch, client, framework_ready):
    from app.services import llm

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Le modele ne doit jamais etre appele : entite hors champ DORA.")

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", fail_if_called)

    email = _email()
    body = _register(client, email)
    org_id = body["memberships"][0]["organization_id"]
    token = _login(client, email)
    headers = {"Authorization": f"Bearer {token}"}

    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.id == uuid.UUID(org_id)))
        org.entite_financiere_dora = False
        db.commit()

    r = client.post(f"/api/v1/orgs/{org_id}/audits", headers=headers,
                    json={"title": "Audit DORA", "framework": "dora"})
    assert r.status_code == 201, r.text
    assert r.json()["scope_warning"] is not None
    audit_id = r.json()["id"]

    r = client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/documents", headers=headers,
        files={"file": ("politique.txt", POLICY.encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 201, r.text

    r = client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/run", headers=headers)
    assert r.status_code == 200, r.text
    outcome = r.json()
    assert outcome["not_applicable"] == 3  # les trois exigences du jeu de test

    r = client.get(f"/api/v1/orgs/{org_id}/audits/{audit_id}/findings", headers=headers)
    findings = r.json()
    assert len(findings) == 3
    assert all(f["status"] == "not_applicable" for f in findings)
    assert all("DORA" in f["description"] for f in findings)
