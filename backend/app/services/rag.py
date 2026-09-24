"""Recherche des passages pertinents sur les exigences et sur les documents
du client, selon la methode choisie par `settings.RAG_RETRIEVER`.

Le filtre par organisation est applique dans la requete SQL elle-meme, et non
apres coup en Python : une fuite inter-locataires est ainsi structurellement
impossible, meme en cas d'erreur applicative en aval.

Trois methodes, mesurees sur le corpus de validation (voir
validation/comparer_retrievers.py, resultats dans
validation/comparaison_retrievers.json, ~210 articles evalues) :

    | Methode    | Exactitude | Precision | Rappel | Faux negatifs |
    |------------|-----------:|----------:|-------:|--------------:|
    | Lexicale   |      91,9 %|     82,1 %|  100 % |             0 |
    | Semantique |      85,2 %|     73,3 %|  94,9 %|             4 |
    | Hybride    |      90,5 %|     81,5 %|  96,2 %|             3 |

Sur des textes reglementaires, la terminologie exacte ("article 30", "72
heures") compte plus que la paraphrase : le lexical seul bat le semantique
seul sur toutes les metriques mesurees, d'ou son choix par defaut
(RAG_RETRIEVER="lexical"). Le mode "hybride" reste disponible : un document
client reel ne reprend pas toujours le vocabulaire exact du texte de loi, et
l'ecart mesure avec le lexical seul (1,4 point) n'est pas significatif sur ce
corpus.

_scores_lexicaux() est une copie adaptee de
evaluation/evaluateur.py::retriever_lexical et de
evaluation/verificateur.py::normaliser -- le backend n'importe jamais le
paquet evaluation (deux paquets separes, voir docs/architecture.md) : toute
correction de l'algorithme doit etre reportee manuellement des deux cotes.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass

from sqlalchemy import select
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


# ---------------------------------------------------------------------------
# Lexical -- copie adaptee de evaluation/evaluateur.py::retriever_lexical
# ---------------------------------------------------------------------------
def _normaliser(texte: str) -> str:
    """Copie fidele de evaluation/verificateur.py::normaliser."""
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = texte.lower()
    texte = texte.replace("’", "'").replace("‘", "'")
    texte = (
        texte.replace("«", '"')
        .replace("»", '"')
        .replace("“", '"')
        .replace("”", '"')
    )
    texte = re.sub(r"[^\w\s']", " ", texte)
    texte = re.sub(r"\s+", " ", texte)
    return texte.strip()


def _scores_lexicaux(requete: str, candidats: list[tuple[str, str]]) -> dict[str, float]:
    """Recouvrement lexical pondere par occurrence et longueur du texte --
    coeur de l'algorithme mesure dans comparaison_retrievers.json.

    candidats : liste de (identifiant, texte). Renvoie un score par
    identifiant (absent si aucun terme ne matche), jamais tronque : les
    appelants decident de la limite et du repli "toujours renvoyer quelque
    chose" (un article sans passage pertinent doit etre evalue -- et
    conclure au manquement -- pas escamote).
    """
    termes = [t for t in _normaliser(requete).split() if len(t) > 3]
    if not termes:
        return {}
    scores: dict[str, float] = {}
    for identifiant, texte in candidats:
        corps = _normaliser(texte)
        score = sum(corps.count(t) for t in termes) / (1 + len(corps) / 800)
        if score > 0:
            scores[identifiant] = score
    return scores


def _classer_lexical(candidats: list[tuple[str, str]], scores: dict[str, float], limit: int) -> list[str]:
    ordre = [i for i, _ in candidats]
    retenus = sorted((i for i in ordre if i in scores), key=lambda i: scores[i], reverse=True)
    return (retenus or ordre)[:limit]


# Approximation d'une distance a partir du score lexical (sans unite propre,
# a la difference d'une distance cosinus) : necessaire pour que le repli
# heuristique de audit_engine.py (sans modele de langage, seuils 0.25/0.45
# sur Passage.distance) reste au moins ORDONNE correctement en mode lexical
# -- un score fort doit produire une distance faible, un score nul une
# distance maximale. Monotone, mais les seuils existants n'ont ete calibres
# que sur la distance cosinus : approximation assumee, pas une mesure.
def _distance_depuis_score_lexical(score: float) -> float:
    return 1.0 / (1.0 + score)


# Constante de la fusion de rangs (Reciprocal Rank Fusion), mode hybride.
# k = 60, meme valeur que le harnais de validation
# (rag/retriever_semantique.py::RetrieverHybride) et que
# validation/comparaison_retrievers.json : reprise a l'identique, pas
# reinventee ici.
RRF_K = 60


def _fusionner_rrf(*classements: list[str], limit: int) -> list[str]:
    scores: dict[str, float] = {}
    for classement in classements:
        for rang, identifiant in enumerate(classement):
            scores[identifiant] = scores.get(identifiant, 0.0) + 1.0 / (RRF_K + rang + 1)
    return sorted(scores, key=lambda i: scores[i], reverse=True)[:limit]


# ---------------------------------------------------------------------------
# Exigences du referentiel
# ---------------------------------------------------------------------------
def search_requirements(
    db: Session,
    query: str,
    framework_code: str,
    limit: int | None = None,
) -> list[Passage]:
    """Retrouve les articles du referentiel les plus proches d'une question."""
    limit = limit or settings.RAG_TOP_K
    methode = settings.RAG_RETRIEVER

    base = (
        select(Requirement)
        .join(FrameworkVersion, Requirement.version_id == FrameworkVersion.id)
        .join(Framework, FrameworkVersion.framework_id == Framework.id)
        .where(
            Framework.code == framework_code,
            FrameworkVersion.is_current.is_(True),
        )
    )

    if methode == "semantique":
        return _requirements_semantique(db, query, base, limit)
    if methode == "hybride":
        return _requirements_hybride(db, query, base, limit)
    return _requirements_lexical(db, query, base, limit)


def _requirements_semantique(db: Session, query: str, base, limit: int) -> list[Passage]:
    vector = _query_vector(query)
    distance = Requirement.embedding.cosine_distance(vector).label("distance")
    rows = db.execute(
        base.where(Requirement.embedding.isnot(None))
        .add_columns(distance)
        .order_by(distance)
        .limit(limit)
    ).all()
    return [_passage_requirement(r, float(d)) for r, d in rows]


def _requirements_lexical(db: Session, query: str, base, limit: int) -> list[Passage]:
    lignes = db.execute(base).scalars().all()
    if not lignes:
        return []
    candidats = [(str(r.id), f"{r.title} {r.body}") for r in lignes]
    scores = _scores_lexicaux(query, candidats)
    par_id = {str(r.id): r for r in lignes}
    classement = _classer_lexical(candidats, scores, limit)
    return [
        _passage_requirement(par_id[i], _distance_depuis_score_lexical(scores.get(i, 0.0)))
        for i in classement
    ]


def _requirements_hybride(db: Session, query: str, base, limit: int) -> list[Passage]:
    lignes = db.execute(base).scalars().all()
    if not lignes:
        return []
    candidats = [(str(r.id), f"{r.title} {r.body}") for r in lignes]
    scores = _scores_lexicaux(query, candidats)
    classement_lexical = _classer_lexical(candidats, scores, max(limit * 3, 10))

    avec_embedding = [r for r in lignes if r.embedding is not None]
    classement_semantique: list[str] = []
    if avec_embedding:
        vector = _query_vector(query)
        distance = Requirement.embedding.cosine_distance(vector).label("distance")
        large = max(limit * 3, 10)
        rows = db.execute(
            base.where(Requirement.embedding.isnot(None))
            .add_columns(distance)
            .order_by(distance)
            .limit(large)
        ).all()
        classement_semantique = [str(r.id) for r, _ in rows]

    fusion = _fusionner_rrf(classement_lexical, classement_semantique, limit=limit)
    par_id = {str(r.id): r for r in lignes}
    return [
        _passage_requirement(par_id[i], _distance_depuis_score_lexical(scores.get(i, 0.0)))
        for i in fusion
        if i in par_id
    ]


def _passage_requirement(r: Requirement, distance: float) -> Passage:
    return Passage(
        text=f"{r.reference} — {r.title}\n{r.body}",
        reference=r.reference,
        distance=distance,
        source=r.source_url or "",
    )


# ---------------------------------------------------------------------------
# Documents du client
# ---------------------------------------------------------------------------
def search_client_documents(
    db: Session,
    query: str,
    organization_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> list[Passage]:
    """Retrouve les passages des documents deposes par le client."""
    limit = limit or settings.RAG_TOP_K
    methode = settings.RAG_RETRIEVER

    # Filtres identiques quelle que soit la methode : organization_id et
    # audit_id restent dans la clause WHERE, jamais appliques apres coup.
    base = (
        select(DocumentChunk, Document.filename)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(DocumentChunk.organization_id == organization_id)
    )
    if audit_id is not None:
        base = base.where(Document.audit_id == audit_id)

    if methode == "semantique":
        return _documents_semantique(db, query, base, limit)
    if methode == "hybride":
        return _documents_hybride(db, query, base, limit)
    return _documents_lexical(db, query, base, limit)


def _documents_semantique(db: Session, query: str, base, limit: int) -> list[Passage]:
    vector = _query_vector(query)
    distance = DocumentChunk.embedding.cosine_distance(vector).label("distance")
    rows = db.execute(
        base.where(DocumentChunk.embedding.isnot(None))
        .add_columns(distance)
        .order_by(distance)
        .limit(limit)
    ).all()
    return [_passage_chunk(c, filename, float(d)) for c, filename, d in rows]


def _documents_lexical(db: Session, query: str, base, limit: int) -> list[Passage]:
    lignes = db.execute(base).all()
    if not lignes:
        return []
    candidats = [(str(c.id), c.content) for c, _ in lignes]
    scores = _scores_lexicaux(query, candidats)
    par_id = {str(c.id): (c, filename) for c, filename in lignes}
    classement = _classer_lexical(candidats, scores, limit)
    return [
        _passage_chunk(
            par_id[i][0], par_id[i][1], _distance_depuis_score_lexical(scores.get(i, 0.0))
        )
        for i in classement
    ]


def _documents_hybride(db: Session, query: str, base, limit: int) -> list[Passage]:
    lignes = db.execute(base).all()
    if not lignes:
        return []
    candidats = [(str(c.id), c.content) for c, _ in lignes]
    scores = _scores_lexicaux(query, candidats)
    classement_lexical = _classer_lexical(candidats, scores, max(limit * 3, 10))

    avec_embedding = [(c, filename) for c, filename in lignes if c.embedding is not None]
    classement_semantique: list[str] = []
    if avec_embedding:
        vector = _query_vector(query)
        distance = DocumentChunk.embedding.cosine_distance(vector).label("distance")
        large = max(limit * 3, 10)
        rows = db.execute(
            base.where(DocumentChunk.embedding.isnot(None))
            .add_columns(distance)
            .order_by(distance)
            .limit(large)
        ).all()
        classement_semantique = [str(c.id) for c, _, _ in rows]

    fusion = _fusionner_rrf(classement_lexical, classement_semantique, limit=limit)
    par_id = {str(c.id): (c, filename) for c, filename in lignes}
    return [
        _passage_chunk(
            par_id[i][0], par_id[i][1], _distance_depuis_score_lexical(scores.get(i, 0.0))
        )
        for i in fusion
        if i in par_id
    ]


def _passage_chunk(chunk: DocumentChunk, filename: str, distance: float) -> Passage:
    return Passage(
        text=chunk.content, reference=filename, distance=distance,
        source=filename, document_id=chunk.document_id,
    )
