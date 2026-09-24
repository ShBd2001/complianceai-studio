"""Les trois methodes de recherche de app/services/rag.py (RAG_RETRIEVER =
"lexical" | "semantique" | "hybride"). Voir DA-07 dans docs/architecture.md
et validation/comparaison_retrievers.json pour la mesure qui justifie le
choix du lexical par defaut.

La suite tourne avec EMBEDDING_BACKEND=hashing (voir conftest.py) : une
projection deterministe mais sans vraie semantique. Les scenarios de ce
fichier sont donc concus pour rester valides quelle que soit la qualite du
"semantique" mesure -- l'isolation multi-tenant et l'absence de doublon ne
dependent d'aucune des deux methodes en particulier.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.db.session import SessionLocal
from app.models.audit import Audit, Document, DocumentChunk
from app.models.enums import AuditStatus
from app.models.enums import Framework as FrameworkCode
from app.models.organization import Organization
from app.services.embeddings import get_embedder
from app.services.rag import search_client_documents

MODES = ["lexical", "semantique", "hybride"]


@pytest.fixture(autouse=True)
def _restaurer_retriever():
    """RAG_RETRIEVER est valide au demarrage (voir config.py) mais reste un
    attribut Pydantic ordinaire, mutable : les tests le changent directement
    plutot que de reinstancier Settings (couteux, et re-obligerait a fournir
    DATABASE_URL/JWT_SECRET a chaque fois)."""
    original = settings.RAG_RETRIEVER
    yield
    settings.RAG_RETRIEVER = original


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
        mime_type="text/plain", size_bytes=len(contenu),
        sha256=uuid.uuid4().hex.ljust(64, "0"), storage_key=f"{org.id}/{uuid.uuid4().hex}.txt",
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


# ---------------------------------------------------------------------------
# Mode lexical : le fragment pertinent doit etre classe en tete
# ---------------------------------------------------------------------------
def test_mode_lexical_classe_en_tete_le_fragment_contenant_les_mots_de_la_requete():
    settings.RAG_RETRIEVER = "lexical"
    with SessionLocal() as db:
        org, audit = _creer_organisation_et_audit(db)
        _ajouter_chunk(db, org, audit, "Un texte totalement hors sujet sur la meteo et le sport.")
        pertinent = _ajouter_chunk(
            db, org, audit,
            "Le registre des activites de traitement est tenu a jour par le "
            "responsable du traitement, conformement a l'article 30.",
        )
        db.commit()

        resultats = search_client_documents(
            db, "registre activites traitement", org.id, limit=1
        )

    assert len(resultats) == 1
    assert resultats[0].document_id == pertinent.document_id


# ---------------------------------------------------------------------------
# Isolation : jamais un fragment d'une autre organisation ou d'une autre
# campagne, quelle que soit la methode.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mode", MODES)
def test_isolation_par_organisation(mode):
    settings.RAG_RETRIEVER = mode
    with SessionLocal() as db:
        org_a, audit_a = _creer_organisation_et_audit(db)
        org_b, audit_b = _creer_organisation_et_audit(db)
        # Contenu identique des deux cotes : si l'isolation reposait sur le
        # contenu plutot que sur le filtre SQL, ce cas la ferait echouer.
        contenu = "Le delegue a la protection des donnees supervise le registre des traitements."
        _ajouter_chunk(db, org_a, audit_a, contenu)
        chunk_b = _ajouter_chunk(db, org_b, audit_b, contenu)
        db.commit()

        resultats = search_client_documents(db, "registre des traitements", org_a.id, limit=5)

    assert resultats
    assert all(r.document_id != chunk_b.document_id for r in resultats)


@pytest.mark.parametrize("mode", MODES)
def test_isolation_par_campagne_dans_la_meme_organisation(mode):
    settings.RAG_RETRIEVER = mode
    with SessionLocal() as db:
        org, audit_1 = _creer_organisation_et_audit(db)
        audit_2 = Audit(
            organization_id=org.id, title="Deuxieme audit", framework=FrameworkCode.RGPD,
            status=AuditStatus.RUNNING,
        )
        db.add(audit_2)
        db.flush()

        contenu = "Politique de securite mentionnant le registre des traitements."
        _ajouter_chunk(db, org, audit_1, contenu)
        chunk_2 = _ajouter_chunk(db, org, audit_2, contenu)
        db.commit()

        resultats = search_client_documents(
            db, "registre des traitements", org.id, audit_id=audit_1.id, limit=5
        )

    assert resultats
    assert all(r.document_id != chunk_2.document_id for r in resultats)


# ---------------------------------------------------------------------------
# Hybride : pas de doublon, jamais plus que top_k
# ---------------------------------------------------------------------------
def test_mode_hybride_sans_doublon_et_au_plus_top_k():
    settings.RAG_RETRIEVER = "hybride"
    with SessionLocal() as db:
        org, audit = _creer_organisation_et_audit(db)
        for i in range(6):
            _ajouter_chunk(
                db, org, audit,
                f"Fragment numero {i} sur le registre des traitements et la "
                "protection des donnees a caractere personnel.",
            )
        db.commit()

        resultats = search_client_documents(
            db, "registre traitements protection donnees", org.id, limit=3
        )

    assert 0 < len(resultats) <= 3
    identifiants = [r.document_id for r in resultats]
    assert len(identifiants) == len(set(identifiants))


# ---------------------------------------------------------------------------
# Configuration invalide refusee au demarrage
# ---------------------------------------------------------------------------
def test_configuration_invalide_est_refusee():
    with pytest.raises(ValidationError):
        Settings(
            RAG_RETRIEVER="invalide",
            DATABASE_URL="postgresql+psycopg://x:x@localhost/x",
            JWT_SECRET="peu-importe-pour-ce-test",
        )
