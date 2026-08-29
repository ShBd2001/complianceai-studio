"""Tests de la chaine complete : referentiel, depot, execution, rapport.

Le referentiel est injecte localement plutot que telecharge : un test ne doit
jamais dependre de la disponibilite d'un service externe.
"""

import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.base import IngestionResult, RawRequirement
from app.ingestion.runner import ingest
from app.main import app
from app.models.enums import Pillar, RequirementKind
from app.models.framework import Framework, FrameworkVersion, Requirement
from conftest import verify_email

PWD = "Compliance!2026x"


class FakeConnector:
    """Connecteur local reproduisant la forme d'une sortie EUR-Lex."""

    code = "rgpd"

    def __init__(self, body_suffix: str = "") -> None:
        self.body_suffix = body_suffix

    def fetch(self) -> IngestionResult:
        articles = [
            # Article 4 : definitions -> hors perimetre d'audit
            ("Article 4", "Definitions",
             "Aux fins du present reglement, on entend par donnees a caractere "
             "personnel toute information se rapportant a une personne physique."),
            ("Article 5", "Principes relatifs au traitement",
             "Les donnees a caractere personnel doivent etre traitees de maniere "
             "licite, loyale et transparente. Elles sont collectees pour des "
             "finalites determinees, explicites et legitimes."),
            ("Article 30", "Registre des activites de traitement",
             "Chaque responsable du traitement tient un registre des activites de "
             "traitement effectuees sous sa responsabilite. Ce registre comporte "
             "les finalites du traitement et les categories de personnes concernees."),
            ("Article 32", "Securite du traitement",
             "Le responsable du traitement met en oeuvre les mesures techniques et "
             "organisationnelles appropriees, notamment le chiffrement des donnees "
             "et la capacite a retablir la disponibilite en cas d'incident."),
            ("Article 33", "Notification des violations",
             "En cas de violation de donnees a caractere personnel, le responsable "
             "du traitement notifie la violation a l'autorite de controle dans les "
             "meilleurs delais et si possible 72 heures au plus tard."),
            # Article 68 : institution du comite europeen -> hors perimetre
            ("Article 68", "Comite europeen de la protection des donnees",
             "Le comite europeen de la protection des donnees est institue en tant "
             "qu'organe de l'Union et dispose de la personnalite juridique."),
        ]
        requirements = [
            RawRequirement(
                reference=ref, title=title, body=body + self.body_suffix,
                kind=RequirementKind.ARTICLE, ordering=i + 1,
                source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            )
            for i, (ref, title, body) in enumerate(articles)
        ]
        return IngestionResult(
            code="rgpd",
            name="Reglement general sur la protection des donnees",
            pillar=Pillar.PRIVACY,
            authority="Parlement europeen et Conseil",
            source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            license="Decision 2011/833/UE",
            celex_id="32016R0679",
            version_label="2016/679",
            effective_date=date(2018, 5, 25),
            requirements=requirements,
            raw_text="\n".join(f"{r.reference} {r.title} {r.body}" for r in requirements),
        )


POLICY = """Politique de protection des donnees personnelles — Acme SAS

1. Finalites du traitement
Les donnees des clients sont collectees pour la gestion des commandes et le
support. Les finalites sont determinees et explicites, conformement aux
principes de licéité et de transparence.

2. Securite
Les donnees sont chiffrees au repos et en transit. Les acces sont restreints
par authentification forte. Des sauvegardes quotidiennes permettent de
retablir la disponibilite des donnees en cas d'incident.

3. Sous-traitance
Les prestataires sont lies par un contrat conforme a l'article 28.
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
    email = f"audit-{uuid.uuid4().hex[:8]}@exemple.fr"
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


# --------------------------------------------------------------------------
# Ingestion et veille
# --------------------------------------------------------------------------
def test_ingestion_creates_versioned_framework(framework_ready):
    with SessionLocal() as db:
        framework = db.scalar(select(Framework).where(Framework.code == "rgpd"))
        assert framework is not None
        assert framework.celex_id == "32016R0679"
        assert framework.is_redistributable is True

        version = db.scalar(
            select(FrameworkVersion).where(
                FrameworkVersion.framework_id == framework.id,
                FrameworkVersion.is_current.is_(True),
            )
        )
        assert version is not None
        assert len(version.source_sha256) == 64


def test_requirements_are_embedded(framework_ready):
    with SessionLocal() as db:
        version = db.scalar(
            select(FrameworkVersion)
            .join(Framework, FrameworkVersion.framework_id == Framework.id)
            .where(Framework.code == "rgpd", FrameworkVersion.is_current.is_(True))
        )
        reqs = list(db.scalars(
            select(Requirement).where(Requirement.version_id == version.id)
        ))
        assert len(reqs) == 6
        assert all(r.embedding is not None for r in reqs)

        auditable = {r.reference for r in reqs if r.is_auditable}
        assert auditable == {"Article 5", "Article 30", "Article 32", "Article 33"}
        # Definitions et institution du comite : hors du champ d'un audit client.
        assert {r.reference for r in reqs if not r.is_auditable} == {
            "Article 4", "Article 68"
        }


def test_unchanged_source_is_not_reingested(framework_ready):
    with SessionLocal() as db:
        report = ingest(db, FakeConnector())
        db.commit()
    assert report.status == "unchanged"


def test_changed_source_creates_new_version(framework_ready):
    """Le dispositif de veille : une empreinte differente cree une version."""
    with SessionLocal() as db:
        before = len(db.scalar(
            select(Framework).where(Framework.code == "rgpd")
        ).versions)

        report = ingest(db, FakeConnector(body_suffix=" Modification 2026."))
        db.commit()

        assert report.status == "updated"
        framework = db.scalar(select(Framework).where(Framework.code == "rgpd"))
        assert len(framework.versions) == before + 1
        current = [v for v in framework.versions if v.is_current]
        assert len(current) == 1
        assert "Evolution detectee" in (current[0].change_note or "")


# --------------------------------------------------------------------------
# API referentiels
# --------------------------------------------------------------------------
def test_frameworks_endpoint_lists_rgpd(client, org, framework_ready):
    _, headers = org
    r = client.get("/api/v1/frameworks", headers=headers)
    assert r.status_code == 200
    codes = {f["code"] for f in r.json()}
    assert "rgpd" in codes


def test_requirements_endpoint_returns_articles(client, org, framework_ready):
    _, headers = org
    r = client.get("/api/v1/frameworks/rgpd/requirements", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 6

    r = client.get(
        "/api/v1/frameworks/rgpd/requirements?auditable_only=true", headers=headers
    )
    assert r.status_code == 200
    assert len(r.json()) == 4
    assert all(item["is_auditable"] for item in r.json())


def test_unknown_framework_gives_actionable_error(client, org, framework_ready):
    """Le message d'erreur doit indiquer la commande a lancer.

    On utilise un code volontairement inexistant plutot qu'un referentiel
    reel : le test ne doit pas dependre de ce qui a ete ingere par ailleurs.
    """
    _, headers = org
    r = client.get("/api/v1/frameworks/referentiel-inexistant/requirements", headers=headers)
    assert r.status_code == 404
    assert "ingestion.cli" in r.json()["detail"]


# --------------------------------------------------------------------------
# Chaine d'audit complete
# --------------------------------------------------------------------------
def test_full_audit_pipeline(client, org, framework_ready):
    org_id, headers = org

    r = client.post(f"/api/v1/orgs/{org_id}/audits", headers=headers,
                    json={"title": "Audit RGPD 2026", "framework": "rgpd"})
    assert r.status_code == 201, r.text
    audit_id = r.json()["id"]
    assert r.json()["status"] == "draft"

    r = client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/documents",
        headers=headers,
        files={"file": ("politique.txt", POLICY.encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 201, r.text
    assert len(r.json()["sha256"]) == 64

    r = client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/run", headers=headers)
    assert r.status_code == 200, r.text
    outcome = r.json()
    assert outcome["status"] == "completed"
    # 6 exigences ingerees, 4 auditables : les definitions et l'institution du
    # comite europeen ne sont pas confrontees aux documents du client.
    assert outcome["evaluated"] == 4

    # Les tests tournent sans cle LLM : le moteur doit refuser de publier un
    # score plutot que d'en presenter un issu de la seule heuristique.
    assert outcome["score"] is None
    assert "sans modele de langage" in outcome["message"]

    r = client.get(f"/api/v1/orgs/{org_id}/audits/{audit_id}/findings", headers=headers)
    assert r.status_code == 200
    findings = r.json()
    # Chaque constat cite un article reel et trace son origine.
    off_scope = {"Article 4", "Article 68"}
    for finding in findings:
        assert finding["article_ref"].startswith("Article")
        assert finding["article_ref"] not in off_scope
        assert finding["model_used"]
        assert finding["confidence"] is not None

    r = client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/reports", headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 1
    assert len(r.json()["sha256"]) == 64

    r = client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/reports", headers=headers)
    assert r.json()["version"] == 2  # versionnement du livrable

    r = client.get(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/reports/1/download", headers=headers
    )
    assert r.status_code == 200
    assert "Rapport d'audit de conformité" in r.text

    r = client.get(f"/api/v1/orgs/{org_id}/audits/history", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_report_pdf_download_returns_valid_pdf_and_is_cached(client, org, framework_ready):
    """Rendu par un vrai navigateur (services/pdf.py) : verifie les octets
    magiques PDF et que le second appel sert le fichier mis en cache sur
    disque (memes octets, pas une nouvelle generation)."""
    org_id, headers = org
    audit_id = client.post(
        f"/api/v1/orgs/{org_id}/audits", headers=headers,
        json={"title": "Audit PDF", "framework": "rgpd"},
    ).json()["id"]
    client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/documents", headers=headers,
        files={"file": ("politique.txt", POLICY.encode("utf-8"), "text/plain")},
    )
    client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/run", headers=headers)
    client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/reports", headers=headers)

    r = client.get(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/reports/1/download.pdf", headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 1000

    r2 = client.get(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/reports/1/download.pdf", headers=headers
    )
    assert r2.status_code == 200
    assert r2.content == r.content  # servi depuis le cache disque


def test_concurrent_report_generation_does_not_duplicate_versions(client, org, framework_ready):
    """Deux requetes "produire un rapport" simultanees pour le meme audit ne
    doivent ni produire deux fois la meme version, ni planter sur la
    contrainte d'unicite en base : le verrou consultatif transactionnel doit
    les serialiser proprement."""
    import threading

    from app.db.session import SessionLocal
    from app.models.audit import Audit
    from app.services import reports

    org_id, headers = org
    audit_id = client.post(
        f"/api/v1/orgs/{org_id}/audits", headers=headers,
        json={"title": "Audit concurrence", "framework": "rgpd"},
    ).json()["id"]
    client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/documents", headers=headers,
        files={"file": ("politique.txt", POLICY.encode("utf-8"), "text/plain")},
    )
    client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/run", headers=headers)

    results: list[object] = []

    def _produire():
        with SessionLocal() as db:
            audit = db.get(Audit, uuid.UUID(audit_id))
            try:
                report = reports.generate_report(db, audit)
                db.commit()
                results.append(report.version)
            except Exception as exc:  # noqa: BLE001 - on veut voir toute erreur
                db.rollback()
                results.append(exc)

    threads = [threading.Thread(target=_produire) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, f"generation concurrente en erreur : {errors}"
    assert sorted(results) == [1, 2]  # deux versions distinctes, pas de doublon


def test_run_without_document_fails_cleanly(client, org, framework_ready):
    org_id, headers = org
    audit_id = client.post(
        f"/api/v1/orgs/{org_id}/audits", headers=headers,
        json={"title": "Audit vide", "framework": "rgpd"},
    ).json()["id"]

    r = client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/run", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
    assert "document" in r.json()["message"].lower()


def test_report_refused_before_completion(client, org, framework_ready):
    org_id, headers = org
    audit_id = client.post(
        f"/api/v1/orgs/{org_id}/audits", headers=headers,
        json={"title": "Audit brouillon", "framework": "rgpd"},
    ).json()["id"]

    r = client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/reports", headers=headers)
    assert r.status_code == 409


def test_unsupported_file_type_rejected(client, org, framework_ready):
    org_id, headers = org
    audit_id = client.post(
        f"/api/v1/orgs/{org_id}/audits", headers=headers,
        json={"title": "Audit", "framework": "rgpd"},
    ).json()["id"]

    r = client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/documents", headers=headers,
        files={"file": ("virus.exe", b"MZ\x90\x00", "application/x-msdownload")},
    )
    assert r.status_code == 415


def test_audit_of_another_org_is_invisible(client, org, framework_ready):
    org_a, headers_a = org

    email_b = f"other-{uuid.uuid4().hex[:8]}@exemple.fr"
    client.post("/api/v1/auth/register", json={
        "email": email_b, "password": PWD, "full_name": "Autre Personne",
        "organization_name": "Beta SARL", "accept_terms": True,
    })
    verify_email(client, email_b)
    token_b = client.post("/api/v1/auth/login",
                          json={"email": email_b, "password": PWD}).json()["access_token"]

    audit_id = client.post(
        f"/api/v1/orgs/{org_a}/audits", headers=headers_a,
        json={"title": "Confidentiel", "framework": "rgpd"},
    ).json()["id"]

    r = client.get(
        f"/api/v1/orgs/{org_a}/audits/{audit_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 404


def test_score_is_withheld_without_language_model(client, org, framework_ready):
    """Un score produit sans modele n'est pas publie.

    C'est le defaut le plus grave qu'un outil d'audit puisse avoir : rendre un
    chiffre credible alors que l'analyse s'est faite a l'aveugle. Le score est
    retire, l'avertissement est porte par l'audit et repris dans le rapport.
    """
    org_id, headers = org
    audit_id = client.post(
        f"/api/v1/orgs/{org_id}/audits", headers=headers,
        json={"title": "Audit sans LLM", "framework": "rgpd"},
    ).json()["id"]

    client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/documents", headers=headers,
        files={"file": ("politique.txt", POLICY.encode("utf-8"), "text/plain")},
    )

    run = client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/run", headers=headers).json()
    assert run["score"] is None
    assert run["message"]

    # Le constat indique son producteur reel, pas ce qui etait disponible.
    findings = client.get(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/findings", headers=headers
    ).json()
    assert all(f["model_used"] == "heuristique" for f in findings)

    # Le rapport porte l'avertissement de facon visible.
    client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/reports", headers=headers)
    report = client.get(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/reports/1/download", headers=headers
    )
    assert "Analyse dégradée" in report.text


# --------------------------------------------------------------------------
# Garde-fous sur le fournisseur de modele
# --------------------------------------------------------------------------
def test_breaker_opens_after_consecutive_failures():
    """Apres N echecs consecutifs, on cesse de solliciter le fournisseur.

    Sans ce disjoncteur, un quota epuise se traduisait par 45 exigences x 3
    tentatives x plusieurs secondes d'attente : un audit pouvait depasser
    l'heure sans jamais aboutir.
    """
    from app.services.audit_engine import Breaker

    breaker = Breaker(threshold=3)
    assert breaker.is_open is False

    breaker.record_failure()
    breaker.record_failure()
    assert breaker.is_open is False

    breaker.record_failure()
    assert breaker.is_open is True


def test_breaker_resets_on_success():
    """Un succes remet le compteur a zero : seuls les echecs consecutifs comptent."""
    from app.services.audit_engine import Breaker

    breaker = Breaker(threshold=3)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.is_open is False


def test_deadline_falls_back_without_calling_the_model(monkeypatch):
    """Passee l'echeance, les exigences restantes ne declenchent aucun appel."""
    import time

    from app.services import audit_engine, llm

    monkeypatch.setattr(llm, "is_available", lambda: True)

    called = []

    def fail_if_called(*args, **kwargs):
        called.append(1)
        raise AssertionError("Le modele ne doit pas etre appele apres l'echeance.")

    monkeypatch.setattr(llm, "complete_json", fail_if_called)

    class FakeRequirement:
        reference = "Article 30"
        title = "Registre des activites de traitement"
        body = "Chaque responsable du traitement tient un registre."

    verdicts = audit_engine._evaluate_all(
        [(FakeRequirement(), [])],
        deadline=time.monotonic() - 1,  # echeance deja depassee
    )

    assert called == []
    assert verdicts[0]["_source"] == "heuristique"


class FakeRequirement:
    reference = "Article 32"
    title = "Sécurité du traitement"
    body = "Les données à caractère personnel doivent être protégées."


def test_verified_citation_is_kept_and_traces_its_source_document(monkeypatch):
    """Une citation retrouvee telle quelle dans les passages est conservee,
    et le document source retenu est celui d'ou elle provient reellement —
    pas systematiquement le premier document depose sur l'audit."""
    from app.services import audit_engine, llm, rag

    monkeypatch.setattr(llm, "is_available", lambda: True)
    doc_id = uuid.uuid4()
    passage = rag.Passage(
        text="Les données sont chiffrées au repos et en transit.",
        reference="p1", distance=0.1, source="politique.txt", document_id=doc_id,
    )
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {
        "conforme": "oui", "severite": "info", "confiance": 0.9,
        "constat": "Chiffrement en place.",
        "preuve": "Les données sont chiffrées au repos et en transit.",
        "recommandation": None,
    })

    verdict = audit_engine.evaluate_requirement(FakeRequirement(), [passage])

    assert verdict["conforme"] == "oui"
    assert verdict["_passage_verifie"] is passage
    assert verdict["_passage_verifie"].document_id == doc_id


def test_unverifiable_citation_downgrades_compliance_to_indetermine(monkeypatch):
    """Le point precis que ce correctif impose : le modele ne peut pas faire
    passer une conformite pour acquise sur une citation qu'il invente. Avant
    ce correctif, `verdict["preuve"]` n'etait jamais confronte au texte
    source — n'importe quelle citation, vraie ou fabriquee, produisait un
    constat de conformite publie tel quel dans le rapport."""
    from app.services import audit_engine, llm, rag

    monkeypatch.setattr(llm, "is_available", lambda: True)
    passage = rag.Passage(
        text="Les données sont chiffrées au repos et en transit.",
        reference="p1", distance=0.1, source="politique.txt", document_id=uuid.uuid4(),
    )
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {
        "conforme": "oui", "severite": "info", "confiance": 0.9,
        "constat": "Chiffrement en place.",
        "preuve": "Une citation entièrement inventée, absente du document.",
        "recommandation": None,
    })

    verdict = audit_engine.evaluate_requirement(FakeRequirement(), [passage])

    assert verdict["conforme"] == "indetermine"
    assert verdict["_passage_verifie"] is None
    assert verdict["confiance"] <= 0.3
    assert "n'a pas pu etre retrouvee" in verdict["constat"]


def test_compliance_claim_with_no_passages_is_downgraded(monkeypatch):
    """Sans passage recupere, aucune citation n'est de toute facon
    verifiable : le modele ne doit pas pouvoir repondre "oui" dans le vide."""
    from app.services import audit_engine, llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {
        "conforme": "oui", "severite": "info", "confiance": 0.9,
        "constat": "Tout va bien.", "preuve": None, "recommandation": None,
    })

    verdict = audit_engine.evaluate_requirement(FakeRequirement(), [])

    assert verdict["conforme"] == "indetermine"


def test_unverified_citation_does_not_affect_non_compliant_verdicts(monkeypatch):
    """La verification ne s'applique qu'aux affirmations de conformite : un
    constat de manquement ("non") n'a pas besoin d'etre desactive par
    prudence, le risque d'un faux "non" est bien moindre que celui d'un faux
    "oui" pour un outil dont c'est justement le metier de signaler les
    manquements."""
    from app.services import audit_engine, llm, rag

    monkeypatch.setattr(llm, "is_available", lambda: True)
    passage = rag.Passage(
        text="Politique de sécurité incomplète.",
        reference="p1", distance=0.4, source="politique.txt", document_id=uuid.uuid4(),
    )
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {
        "conforme": "non", "severite": "major", "confiance": 0.7,
        "constat": "Aucune mesure de chiffrement mentionnée.",
        "preuve": "Une citation qui ne correspond a rien dans le passage fourni.",
        "recommandation": "Documenter le chiffrement.",
    })

    verdict = audit_engine.evaluate_requirement(FakeRequirement(), [passage])

    assert verdict["conforme"] == "non"


# --------------------------------------------------------------------------
# Exigences hors perimetre
# --------------------------------------------------------------------------
def test_not_applicable_is_excluded_from_score(client, org, framework_ready, monkeypatch):
    """Une exigence non applicable ne doit ni penaliser ni gonfler le score.

    Sur un audit reel, 20 articles du RGPD portant sur des situations absentes
    de l'activite auditee (donnees penales, profilage, codes de conduite
    sectoriels) etaient comptes comme des constats et pesaient dans le
    denominateur. Une PME etait notee sur des obligations qui ne la
    concernaient pas.
    """
    from app.services import audit_engine, llm

    monkeypatch.setattr(llm, "is_available", lambda: True)

    # Deux exigences applicables et satisfaites, deux hors perimetre.
    verdicts = iter([
        {"conforme": "oui", "severite": "info", "confiance": 0.9,
         "constat": "Traite.", "recommandation": None},
        {"conforme": "non_applicable", "severite": "info", "confiance": 0.8,
         "constat": "L'organisation ne traite pas de donnees de sante.",
         "recommandation": None},
        {"conforme": "oui", "severite": "info", "confiance": 0.9,
         "constat": "Traite.", "recommandation": None},
        {"conforme": "non_applicable", "severite": "info", "confiance": 0.8,
         "constat": "Aucune decision automatisee.", "recommandation": None},
    ])
    monkeypatch.setattr(
        audit_engine, "evaluate_requirement",
        lambda *args, **kwargs: {**next(verdicts), "_source": "llm"},
    )

    org_id, headers = org
    audit_id = client.post(
        f"/api/v1/orgs/{org_id}/audits", headers=headers,
        json={"title": "Audit avec hors perimetre", "framework": "rgpd"},
    ).json()["id"]
    client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/documents", headers=headers,
        files={"file": ("politique.txt", POLICY.encode("utf-8"), "text/plain")},
    )

    run = client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/run", headers=headers
    ).json()

    assert run["not_applicable"] == 2
    # Les deux exigences applicables sont satisfaites : score parfait, sans
    # que les deux exclusions ne le tirent vers le haut ni vers le bas.
    assert run["score"] == 100.0

    findings = client.get(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/findings", headers=headers
    ).json()
    excluded = [f for f in findings if f["kind"] == "non_applicable"]
    assert len(excluded) == 2
    # L'exclusion reste tracable et motivee.
    assert all(f["description"] for f in excluded)
    assert all(f["recommendation"] is None for f in excluded)


def test_report_lists_out_of_scope_requirements(client, org, framework_ready, monkeypatch):
    """Le rapport expose les exclusions pour qu'elles soient contestables."""
    from app.services import audit_engine, llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(
        audit_engine, "evaluate_requirement",
        lambda *args, **kwargs: {
            "_source": "llm", "conforme": "non_applicable", "severite": "info",
            "confiance": 0.8, "constat": "Situation absente de l'activite auditee.",
            "recommandation": None,
        },
    )

    org_id, headers = org
    audit_id = client.post(
        f"/api/v1/orgs/{org_id}/audits", headers=headers,
        json={"title": "Audit integralement hors perimetre", "framework": "rgpd"},
    ).json()["id"]
    client.post(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/documents", headers=headers,
        files={"file": ("politique.txt", POLICY.encode("utf-8"), "text/plain")},
    )
    client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/run", headers=headers)
    client.post(f"/api/v1/orgs/{org_id}/audits/{audit_id}/reports", headers=headers)

    report = client.get(
        f"/api/v1/orgs/{org_id}/audits/{audit_id}/reports/1/download", headers=headers
    )
    assert "Exigences hors périmètre" in report.text
    # html.escape convertit l'apostrophe en &#x27; : on verifie un fragment
    # sans caractere echappe plutot que d'affaiblir l'echappement.
    assert "Situation absente de l" in report.text
    assert "activite auditee." in report.text
