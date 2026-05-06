"""
Retrieval sémantique.

Même signature que `retriever_lexical` : (requete, passages, k) -> list[Passage].
On peut donc les substituer l'un à l'autre et comparer sur le même corpus, avec
le même harnais. C'est la seule expérience du projet où une seule variable change.

Deux implémentations :

  - RetrieverLocal    : embeddings calculés à la volée, sans base. Suffisant pour
                        la validation, et c'est ce qu'il faut pour mesurer le gain.
  - RetrieverPgVector : embeddings persistés en base, filtrés par tenant. C'est la
                        version de production.

Le modèle d'embedding est celui déjà retenu pour le projet :
`paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions, multilingue, bon en
français, léger).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from rag.chunking import Passage

logger = logging.getLogger(__name__)

MODELE_EMBEDDING = "paraphrase-multilingual-MiniLM-L12-v2"
DIMENSIONS = 384


# ---------------------------------------------------------------------------
# Version locale — pour mesurer le gain sur le corpus de validation
# ---------------------------------------------------------------------------

@dataclass
class RetrieverLocal:
    """
    Retrieval sémantique sans base de données.

    Les embeddings des passages sont calculés une fois par document et mis en
    cache sur le contenu, ce qui évite de les recalculer à chaque article : un
    document est interrogé une vingtaine de fois par audit.
    """

    modele: str = MODELE_EMBEDDING
    _encodeur: Any = field(default=None, repr=False)
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "pip install sentence-transformers  (installe aussi torch, ~2 Go)"
            ) from exc
        self._encodeur = SentenceTransformer(self.modele)

    def _vecteurs(self, passages: Sequence[Passage]):
        import numpy as np

        cle = str(hash(tuple(p.identifiant + p.texte[:60] for p in passages)))
        if cle not in self._cache:
            textes = [f"{p.section}\n{p.texte}" for p in passages]
            self._cache[cle] = self._encodeur.encode(
                textes, normalize_embeddings=True, show_progress_bar=False
            )
        return np.asarray(self._cache[cle])

    def __call__(
        self, requete: str, passages: Sequence[Passage], k: int
    ) -> list[Passage]:
        if not passages:
            return []
        import numpy as np

        matrice = self._vecteurs(passages)
        vecteur = self._encodeur.encode(
            [requete], normalize_embeddings=True, show_progress_bar=False
        )[0]
        # Vecteurs normalisés : le produit scalaire est la similarité cosinus.
        scores = matrice @ np.asarray(vecteur)
        ordre = np.argsort(-scores)[:k]
        return [passages[i] for i in ordre]


# ---------------------------------------------------------------------------
# Version hybride — recommandée
# ---------------------------------------------------------------------------

@dataclass
class RetrieverHybride:
    """
    Combine lexical et sémantique par fusion de rangs (Reciprocal Rank Fusion).

    Le sémantique retrouve les reformulations ; le lexical reste imbattable sur
    les termes réglementaires exacts — « 72 heures », « clauses contractuelles
    types », « article 30 ». Sur un corpus juridique, les deux se complètent, et
    l'hybride bat presque toujours chacun pris isolément.
    """

    semantique: RetrieverLocal
    constante: int = 60  # amortit le poids des premiers rangs

    def __call__(
        self, requete: str, passages: Sequence[Passage], k: int
    ) -> list[Passage]:
        from evaluation.evaluateur import retriever_lexical

        if not passages:
            return []

        large = min(len(passages), max(k * 2, 10))
        lex = retriever_lexical(requete, passages, large)
        sem = self.semantique(requete, passages, large)

        scores: dict[str, float] = {}
        index: dict[str, Passage] = {}
        for classement in (lex, sem):
            for rang, p in enumerate(classement):
                scores[p.identifiant] = scores.get(p.identifiant, 0.0) + 1.0 / (
                    self.constante + rang + 1
                )
                index[p.identifiant] = p

        meilleurs = sorted(scores, key=lambda i: scores[i], reverse=True)[:k]
        return [index[i] for i in meilleurs]


# ---------------------------------------------------------------------------
# Version production — pgvector
# ---------------------------------------------------------------------------

MIGRATION_PGVECTOR = f"""
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE passages
  ADD COLUMN IF NOT EXISTS embedding vector({DIMENSIONS});

-- Le tenant_id est dans la clause WHERE de la recherche, pas appliqué après :
-- un index HNSW interrogé sans filtre renvoie les voisins tous tenants confondus.
CREATE INDEX IF NOT EXISTS idx_passages_embedding
  ON passages USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_passages_tenant_doc
  ON passages (tenant_id, document_id);
"""

REQUETE_VOISINS = """
SELECT p.identifiant, p.texte, p.section, p.debut, p.fin,
       1 - (p.embedding <=> %(vecteur)s::vector) AS similarite
FROM passages p
WHERE p.tenant_id = %(tenant_id)s
  AND p.document_id = %(document_id)s
  AND p.embedding IS NOT NULL
ORDER BY p.embedding <=> %(vecteur)s::vector
LIMIT %(k)s;
"""


@dataclass
class RetrieverPgVector:
    """
    Retrieval sémantique persisté. Version de production.

    La connexion doit avoir été ouverte avec `securite.multi_tenant.ouvrir_session`
    afin que la RLS s'applique. Le filtre tenant figure malgré tout explicitement
    dans la requête : ceinture et bretelles.
    """

    connexion: Any
    document_id: str
    modele: str = MODELE_EMBEDDING
    _encodeur: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self._encodeur = SentenceTransformer(self.modele)

    def indexer(self, passages: Sequence[Passage], tenant_id: str) -> int:
        textes = [f"{p.section}\n{p.texte}" for p in passages]
        vecteurs = self._encodeur.encode(textes, normalize_embeddings=True)
        with self.connexion.cursor() as cur:
            for p, v in zip(passages, vecteurs):
                cur.execute(
                    """
                    INSERT INTO passages
                      (tenant_id, document_id, identifiant, texte, section,
                       debut, fin, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, document_id, identifiant)
                    DO UPDATE SET texte = EXCLUDED.texte,
                                  embedding = EXCLUDED.embedding;
                    """,
                    (tenant_id, self.document_id, p.identifiant, p.texte,
                     p.section, p.debut, p.fin, list(map(float, v))),
                )
        self.connexion.commit()
        return len(passages)

    def __call__(
        self, requete: str, passages: Sequence[Passage], k: int
    ) -> list[Passage]:
        from securite.multi_tenant import controler_resultats, tenant_actuel

        tenant = tenant_actuel()
        vecteur = self._encodeur.encode([requete], normalize_embeddings=True)[0]

        with self.connexion.cursor() as cur:
            cur.execute(
                REQUETE_VOISINS,
                {
                    "vecteur": list(map(float, vecteur)),
                    "tenant_id": tenant,
                    "document_id": self.document_id,
                    "k": k,
                },
            )
            lignes = [
                dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()
            ]

        controler_resultats(
            [{**l, "tenant_id": tenant} for l in lignes], tenant
        )

        if not lignes:
            logger.warning(
                "pgvector n'a renvoyé aucun passage — index vide ? Repli sur le lexical."
            )
            from evaluation.evaluateur import retriever_lexical

            return retriever_lexical(requete, passages, k)

        par_id = {p.identifiant: p for p in passages}
        return [par_id[l["identifiant"]] for l in lignes if l["identifiant"] in par_id]
