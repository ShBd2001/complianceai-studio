"""Recherche hybride (lexicale + semantique) sur les exigences et sur les
documents du client.

Le filtre par organisation est applique dans la requete SQL elle-meme, et non
apres coup en Python : une fuite inter-locataires est ainsi structurellement
impossible, meme en cas d'erreur applicative en aval.

Hybride par fusion de rangs (Reciprocal Rank Fusion) entre deux classements
independants -- semantique (pgvector, distance cosinus) et lexical (recherche
plein texte Postgres, configuration 'french', colonnes generees `tsv` -- voir
la migration 0013) -- plutot que le seul semantique utilise jusqu'ici.

Mesure sur le corpus de validation (voir validation/comparer_retrievers.py,
comparaison_retrievers.json) : sur des textes reglementaires, le lexical seul
bat le semantique seul sur toutes les metriques (exactitude 91,9 % contre
85,2 %, rappel parfait) -- la terminologie exacte ("article 30", "72 heures")
y compte plus que la paraphrase. Mais un document client reel ne reprend pas
toujours ce vocabulaire au mot pres, d'ou la fusion plutot que le lexical
seul : l'ecart avec l'hybride mesure (90,5 %) n'est pas significatif sur ce
corpus, et l'hybride recupere les reformulations que le lexical manquerait.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audit import Document, DocumentChunk
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


# Constante de la fusion de rangs (Reciprocal Rank Fusion) : amortit le poids
# des tout premiers rangs. Valeur usuelle, deja retenue par le harnais de
# validation (rag/retriever_semantique.py::RetrieverHybride) plutot
# qu'inventee ici sans la mesurer independamment.
RRF_CONSTANTE = 60


def _fusionner(*classements: list[str], limit: int) -> list[str]:
    """Fusion de rangs : combine plusieurs classements d'identifiants (le
    premier de chaque liste compte le plus) en un seul. Ne compare jamais les
    scores d'origine entre eux -- une distance cosinus et un ts_rank_cd ne
    sont pas sur la meme echelle, seuls leurs RANGS le sont."""
    scores: dict[str, float] = {}
    for classement in classements:
        for rang, identifiant in enumerate(classement):
            scores[identifiant] = scores.get(identifiant, 0.0) + 1.0 / (
                RRF_CONSTANTE + rang + 1
            )
    return sorted(scores, key=lambda i: scores[i], reverse=True)[:limit]


def search_requirements(
    db: Session,
    query: str,
    framework_code: str,
    limit: int | None = None,
) -> list[Passage]:
    """Retrouve les articles du referentiel les plus proches d'une question."""
    limit = limit or settings.RAG_TOP_K
    # Bassin plus large que ce qui est rendu : chaque classement individuel
    # doit pouvoir apporter ses propres candidats a la fusion, pas seulement
    # ceux deja en tete de l'autre.
    large = max(limit * 3, 10)
    vector = _query_vector(query)

    base = (
        select(Requirement.id)
        .join(FrameworkVersion, Requirement.version_id == FrameworkVersion.id)
        .join(Framework, FrameworkVersion.framework_id == Framework.id)
        .where(
            Framework.code == framework_code,
            FrameworkVersion.is_current.is_(True),
            Requirement.embedding.isnot(None),
        )
    )

    distance = Requirement.embedding.cosine_distance(vector)
    semantiques = db.execute(base.order_by(distance).limit(large)).scalars().all()

    tsquery = func.plainto_tsquery("french", query)
    lexicaux = (
        db.execute(
            base.where(Requirement.tsv.op("@@")(tsquery))
            .order_by(func.ts_rank_cd(Requirement.tsv, tsquery).desc())
            .limit(large)
        )
        .scalars()
        .all()
    )

    fusion = _fusionner(
        [str(i) for i in semantiques], [str(i) for i in lexicaux], limit=limit
    )
    if not fusion:
        return []

    lignes = db.execute(
        select(Requirement, distance.label("distance")).where(
            Requirement.id.in_([uuid.UUID(i) for i in fusion])
        )
    ).all()
    par_id = {str(r.id): (r, float(d)) for r, d in lignes}

    return [
        Passage(
            text=f"{par_id[i][0].reference} — {par_id[i][0].title}\n{par_id[i][0].body}",
            reference=par_id[i][0].reference,
            distance=par_id[i][1],
            source=par_id[i][0].source_url or "",
        )
        for i in fusion
        if i in par_id
    ]


def search_client_documents(
    db: Session,
    query: str,
    organization_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> list[Passage]:
    """Retrouve les passages des documents deposes par le client."""
    limit = limit or settings.RAG_TOP_K
    large = max(limit * 3, 10)
    vector = _query_vector(query)

    base = select(DocumentChunk.id).where(
        DocumentChunk.organization_id == organization_id,  # cloisonnement SQL
        DocumentChunk.embedding.isnot(None),
    )
    if audit_id is not None:
        base = base.join(Document, DocumentChunk.document_id == Document.id).where(
            Document.audit_id == audit_id
        )

    distance = DocumentChunk.embedding.cosine_distance(vector)
    semantiques = db.execute(base.order_by(distance).limit(large)).scalars().all()

    tsquery = func.plainto_tsquery("french", query)
    lexicaux = (
        db.execute(
            base.where(DocumentChunk.tsv.op("@@")(tsquery))
            .order_by(func.ts_rank_cd(DocumentChunk.tsv, tsquery).desc())
            .limit(large)
        )
        .scalars()
        .all()
    )

    fusion = _fusionner(
        [str(i) for i in semantiques], [str(i) for i in lexicaux], limit=limit
    )
    if not fusion:
        return []

    lignes = db.execute(
        select(DocumentChunk, Document.filename, distance.label("distance"))
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(DocumentChunk.id.in_([uuid.UUID(i) for i in fusion]))
    ).all()
    par_id = {str(c.id): (c, filename, float(d)) for c, filename, d in lignes}

    return [
        Passage(
            text=par_id[i][0].content,
            reference=par_id[i][1],
            distance=par_id[i][2],
            source=par_id[i][1],
            document_id=par_id[i][0].document_id,
        )
        for i in fusion
        if i in par_id
    ]
