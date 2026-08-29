"""Recherche semantique sur les exigences et sur les documents du client.

Le filtre par organisation est applique dans la requete SQL elle-meme, et non
apres coup en Python : une fuite inter-locataires est ainsi structurellement
impossible, meme en cas d'erreur applicative en aval.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audit import DocumentChunk
from app.models.framework import Framework, FrameworkVersion, Requirement
from app.services.embeddings import FastEmbedEmbedder, get_embedder


@dataclass(slots=True)
class Passage:
    text: str
    reference: str
    distance: float
    source: str
    # Uniquement renseigne pour les passages de documents client (recherche
    # sur le referentiel : None). Permet a l'appelant de retrouver le vrai
    # document source d'une citation verifiee, plutot que de le supposer.
    document_id: uuid.UUID | None = None


def _query_vector(text: str) -> list[float]:
    embedder = get_embedder()
    if isinstance(embedder, FastEmbedEmbedder):
        return embedder.embed_query(text)
    return embedder.embed_one(text)


def search_requirements(
    db: Session,
    query: str,
    framework_code: str,
    limit: int | None = None,
) -> list[Passage]:
    """Retrouve les articles du referentiel les plus proches d'une question."""
    vector = _query_vector(query)
    limit = limit or settings.RAG_TOP_K

    distance = Requirement.embedding.cosine_distance(vector).label("distance")
    rows = db.execute(
        select(Requirement, distance)
        .join(FrameworkVersion, Requirement.version_id == FrameworkVersion.id)
        .join(Framework, FrameworkVersion.framework_id == Framework.id)
        .where(
            Framework.code == framework_code,
            FrameworkVersion.is_current.is_(True),
            Requirement.embedding.isnot(None),
        )
        .order_by(distance)
        .limit(limit)
    ).all()

    return [
        Passage(
            text=f"{r.reference} — {r.title}\n{r.body}",
            reference=r.reference,
            distance=float(d),
            source=r.source_url or "",
        )
        for r, d in rows
    ]


def search_client_documents(
    db: Session,
    query: str,
    organization_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> list[Passage]:
    """Retrouve les passages des documents deposes par le client."""
    from app.models.audit import Document

    vector = _query_vector(query)
    limit = limit or settings.RAG_TOP_K

    distance = DocumentChunk.embedding.cosine_distance(vector).label("distance")
    stmt = (
        select(DocumentChunk, Document.filename, distance)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(
            DocumentChunk.organization_id == organization_id,  # cloisonnement SQL
            DocumentChunk.embedding.isnot(None),
        )
        .order_by(distance)
        .limit(limit)
    )
    if audit_id is not None:
        stmt = stmt.where(Document.audit_id == audit_id)

    rows = db.execute(stmt).all()
    return [
        Passage(
            text=c.content, reference=filename, distance=float(d), source=filename,
            document_id=c.document_id,
        )
        for c, filename, d in rows
    ]
