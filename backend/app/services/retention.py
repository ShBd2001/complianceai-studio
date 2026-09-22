"""Retention personnalisee des documents deposes (offre Cabinet).

Purge le contenu (fichier stocke + texte extrait indexe pour la recherche)
des documents plus vieux que la retention configuree par l'organisation --
jamais les constats (Finding) ni le rapport (Report) deja produits, qui
restent la preuve de l'audit meme apres que le document source a disparu.
Voir DA-04 (docs/architecture.md) : contrairement a activity_logs, purger
un Document ne touche pas au journal d'audit, qui reste lui strictement
en ajout seul.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.audit import Document, DocumentChunk
from app.models.organization import Organization
from app.services.documents import storage_root

logger = logging.getLogger("complianceai.retention")

# Plancher impose a toute retention personnalisee : en dessous, le risque
# qu'un client purge par erreur des documents encore utiles pour son propre
# suivi depasse le benefice de minimisation. Applique cote schema (voir
# app/schemas/organization.py), rappele ici pour que le service reste
# coherent meme appele hors API (script, tache differee).
RETENTION_MIN_JOURS = 30


def purge_expired_documents(db: Session) -> int:
    """Purge tous les documents dus, toutes organisations confondues.

    Appelee par le planificateur (app/services/scheduler.py) ; peut aussi
    etre appelee directement dans un test ou un script ponctuel. Retourne
    le nombre de documents purges.
    """
    organisations = db.scalars(
        select(Organization).where(Organization.document_retention_days.isnot(None))
    ).all()

    total = 0
    for org in organisations:
        total += _purger_organisation(db, org)
    if total:
        logger.info("Purge retention : %d document(s) purge(s).", total)
    return total


def _purger_organisation(db: Session, org: Organization) -> int:
    seuil = datetime.now(timezone.utc) - timedelta(days=org.document_retention_days)
    documents = db.scalars(
        select(Document).where(
            Document.organization_id == org.id,
            Document.created_at < seuil,
            Document.content_purged_at.is_(None),
        )
    ).all()

    for document in documents:
        _purger_document(db, document)

    return len(documents)


def _purger_document(db: Session, document: Document) -> None:
    chemin = storage_root() / document.storage_key
    try:
        chemin.unlink(missing_ok=True)
    except OSError:
        # Le fichier peut deja avoir disparu (stockage ephemere, voir
        # render.yaml) : la purge logique (chunks + horodatage) prime, pas
        # une erreur disque secondaire.
        logger.warning("Purge retention : fichier introuvable pour document %s.", document.id)

    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    document.content_purged_at = datetime.now(timezone.utc)
