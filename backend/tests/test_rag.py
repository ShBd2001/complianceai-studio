"""Recherche hybride (lexicale + semantique), voir app/services/rag.py.

La fusion de rangs (_fusionner) est testee isolement, sans base ni
embeddings : c'est un algorithme pur, deterministe, qui n'a pas besoin
d'infrastructure pour etre verifie. Les fonctions de recherche elles-memes
sont testees contre une vraie base Postgres (comme le reste du depot) -- la
suite tourne avec EMBEDDING_BACKEND=hashing (voir conftest.py), une
projection deterministe mais sans vraie semantique : les scenarios ci-dessous
sont donc concus pour rester valides quelle que soit la qualite du "semantique"
utilise, la partie qui compte reellement a verifier ici etant lexicale
(recherche plein texte Postgres, configuration 'french', voir la migration
0013) et la fusion elle-meme.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.db.session import SessionLocal
from app.models.audit import Audit, Document, DocumentChunk
from app.models.enums import AuditStatus, Framework as FrameworkCode, RequirementKind
from app.models.framework import Framework, FrameworkVersion, Requirement
from app.models.organization import Organization
from app.services.embeddings import get_embedder
from app.services.rag import _fusionner, search_client_documents, search_requirements


# ---------------------------------------------------------------------------
# Fusion de rangs : algorithme pur, sans base
# ---------------------------------------------------------------------------
def test_fusionner_inclut_ce_qui_n_apparait_que_dans_un_seul_classement():
    resultat = _fusionner(["a", "b"], ["c"], limit=10)
    assert set(resultat) == {"a", "b", "c"}


def test_fusionner_priorise_ce_qui_apparait_dans_les_deux_classements():
    # "b" est second dans les deux listes ; "a" et "c" ne sont chacun que
    # premier d'un seul classement. Un identifiant present dans les DEUX
    # classements doit l'emporter sur un identifiant present dans un seul,
    # meme mieux classe localement -- c'est tout l'interet de la fusion.
    resultat = _fusionner(["a", "b"], ["c", "b"], limit=1)
    assert resultat == ["b"]


def test_fusionner_respecte_la_limite():
    resultat = _fusionner(["a", "b", "c"], ["d", "e"], limit=2)
    assert len(resultat) == 2


def test_fusionner_sans_aucun_classement_renvoie_une_liste_vide():
    assert _fusionner(limit=5) == []


def test_fusionner_avec_des_listes_vides_renvoie_une_liste_vide():
    assert _fusionner([], [], limit=5) == []


# ---------------------------------------------------------------------------
# Recherche plein texte Postgres : la stemming francaise est le mecanisme
# dont depend tout l'apport du lexical (voir la justification dans
# app/services/rag.py) -- verifiee ici directement en SQL, independamment
# de tout embedding.
# ---------------------------------------------------------------------------
def test_configuration_francaise_matche_des_flexions_differentes():
    with SessionLocal() as db:
        matche = db.execute(
            text(
                "SELECT to_tsvector('french', 'Les données sont traitées.') "
                "@@ plainto_tsquery('french', 'traitement')"
            )
        ).scalar()
        assert matche is True


# ---------------------------------------------------------------------------
# search_requirements
# ---------------------------------------------------------------------------
@pytest.fixture
def referentiel_test():
    """Deux articles au contenu tres distinct, pour verifier que la
    recherche retrouve bien le bon sans confondre les deux."""
    with SessionLocal() as db:
        embedder = get_embedder()
        framework = Framework(
            code=f"test-rag-{uuid.uuid4().hex[:8]}", name="Referentiel de test RAG",
            pillar="privacy", authority="Test", source_url="https://exemple.fr",
            license="Test",
        )
        db.add(framework)
        db.flush()
        version = FrameworkVersion(
            framework_id=framework.id, label="2026", source_sha256="0" * 64,
            ingested_at=datetime.now(timezone.utc), is_current=True,
        )
        db.add(version)
        db.flush()

        textes = {
            "registre": (
                "Article 30", "Registre des activites de traitement",
                "Chaque responsable du traitement tient un registre des "
                "activites de traitement effectuees sous sa responsabilite.",
            ),
            "violation": (
                "Article 33", "Notification des violations",
                "En cas de violation de donnees a caractere personnel, le "
                "responsable du traitement notifie l'autorite de controle "
                "dans les meilleurs delais et si possible sous 72 heures.",
            ),
        }
        vecteurs = embedder.embed([f"{t} {c}" for _, t, c in textes.values()])
        requirements = {}
        for (cle, (ref, titre, corps)), vecteur in zip(textes.items(), vecteurs, strict=True):
            req = Requirement(
                version_id=version.id, reference=ref, title=titre, body=corps,
                kind=RequirementKind.ARTICLE, is_auditable=True, embedding=vecteur,
            )
            db.add(req)
            requirements[cle] = req
        db.flush()
        db.commit()
        yield framework.code, {cle: r.id for cle, r in requirements.items()}

        with SessionLocal() as nettoyage:
            nettoyage.delete(nettoyage.get(Framework, framework.id))
            nettoyage.commit()


def test_search_requirements_trouve_l_article_par_mot_cle_exact(referentiel_test):
    code, ids = referentiel_test
    with SessionLocal() as db:
        resultats = search_requirements(db, "notification violation 72 heures", code, limit=1)
    assert len(resultats) == 1
    assert resultats[0].reference == "Article 33"


def test_search_requirements_filtre_par_referentiel_et_version_courante(referentiel_test):
    code, ids = referentiel_test
    with SessionLocal() as db:
        # Un code de referentiel inexistant ne doit renvoyer aucun resultat,
        # jamais ceux d'un autre referentiel par erreur de filtrage.
        resultats = search_requirements(db, "registre traitement", "code-inexistant-xyz", limit=5)
    assert resultats == []


def test_search_requirements_respecte_la_limite(referentiel_test):
    code, ids = referentiel_test
    with SessionLocal() as db:
        resultats = search_requirements(db, "traitement donnees", code, limit=1)
    assert len(resultats) == 1


# ---------------------------------------------------------------------------
# search_client_documents
# ---------------------------------------------------------------------------
def _creer_organisation_et_audit(db) -> tuple[Organization, Audit]:
    org = Organization(
        name=f"Org test RAG {uuid.uuid4().hex[:6]}", slug=f"org-rag-{uuid.uuid4().hex[:8]}",
        country="FR",
    )
    db.add(org)
    db.flush()
    audit = Audit(
        organization_id=org.id, title="Audit test RAG", framework=FrameworkCode.RGPD,
        status=AuditStatus.RUNNING,
    )
    db.add(audit)
    db.flush()
    return org, audit


def _ajouter_chunk(db, org: Organization, audit: Audit, contenu: str) -> DocumentChunk:
    document = Document(
        audit_id=audit.id, organization_id=org.id, filename="politique.txt",
        mime_type="text/plain", size_bytes=len(contenu), sha256=uuid.uuid4().hex.ljust(64, "0"),
        storage_key=f"{org.id}/test.txt",
    )
    db.add(document)
    db.flush()
    vecteur = get_embedder().embed_one(contenu)
    chunk = DocumentChunk(
        document_id=document.id, organization_id=org.id, chunk_index=0,
        content=contenu, embedding=vecteur, meta={},
    )
    db.add(chunk)
    db.flush()
    return chunk


def test_search_client_documents_isole_par_organisation():
    with SessionLocal() as db:
        org_a, audit_a = _creer_organisation_et_audit(db)
        org_b, audit_b = _creer_organisation_et_audit(db)
        contenu = "Le delegue a la protection des donnees supervise le registre des traitements."
        _ajouter_chunk(db, org_a, audit_a, contenu)
        _ajouter_chunk(db, org_b, audit_b, contenu)
        db.commit()

        resultats_a = search_client_documents(db, "registre des traitements", org_a.id)
        resultats_b = search_client_documents(db, "registre des traitements", org_b.id)

    assert len(resultats_a) == 1
    assert len(resultats_b) == 1
    # Meme contenu texte des deux cotes : seule l'organisation_id distingue
    # les deux morceaux, et chaque recherche ne doit voir que le sien.
    assert resultats_a[0].document_id != resultats_b[0].document_id


def test_search_client_documents_filtre_par_audit_quand_precise():
    with SessionLocal() as db:
        org, audit_1 = _creer_organisation_et_audit(db)
        audit_2 = Audit(
            organization_id=org.id, title="Deuxieme audit", framework=FrameworkCode.RGPD,
            status=AuditStatus.RUNNING,
        )
        db.add(audit_2)
        db.flush()

        _ajouter_chunk(db, org, audit_1, "Contenu du premier audit sur le registre.")
        _ajouter_chunk(db, org, audit_2, "Contenu du deuxieme audit sur le registre.")
        db.commit()

        resultats = search_client_documents(db, "registre", org.id, audit_id=audit_1.id, limit=5)

    assert len(resultats) == 1
    assert "premier audit" in resultats[0].text


def test_search_client_documents_retrouve_une_flexion_differente_du_terme_cherche():
    """Le point precis que le lexical seul (stemming francais) apporte par
    rapport au hachage utilise en test pour le "semantique" : une
    reformulation qui ne partage aucun mot exact avec la requete doit quand
    meme etre retrouvee grace a la racine commune ("traite" / "traitement"),
    pas seulement les documents qui repetent le mot au mot pres."""
    with SessionLocal() as db:
        org, audit = _creer_organisation_et_audit(db)
        _ajouter_chunk(
            db, org, audit,
            "Les donnees des clients sont traitees dans le respect de la "
            "reglementation en vigueur, avec des garanties appropriees.",
        )
        db.commit()

        resultats = search_client_documents(db, "traitement des donnees", org.id, limit=5)

    assert len(resultats) == 1


def test_search_client_documents_sans_aucun_document_renvoie_une_liste_vide():
    with SessionLocal() as db:
        org, _audit = _creer_organisation_et_audit(db)
        db.commit()
        resultats = search_client_documents(db, "peu importe la question", org.id)
    assert resultats == []
