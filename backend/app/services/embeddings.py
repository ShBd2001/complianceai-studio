"""Vectorisation du texte.

Deux implementations derriere une interface commune :

- FastEmbedEmbedder : modele multilingue ONNX execute localement. Gratuit,
  sans appel reseau apres le telechargement initial, adapte au francais.
- HashingEmbedder : repli deterministe sans dependance. La qualite semantique
  est nulle, mais il permet de faire tourner l'application et les tests sans
  telecharger de modele. Jamais utilise en production.

Le choix est fait au demarrage selon la configuration et la disponibilite du
paquet, jamais au milieu d'un traitement.
"""

from __future__ import annotations

import hashlib
import logging
import math
from abc import ABC, abstractmethod
from functools import lru_cache

from app.core.config import settings

logger = logging.getLogger(__name__)


class Embedder(ABC):
    dimension: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Retourne un vecteur normalise par texte."""

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class HashingEmbedder(Embedder):
    """Projection deterministe par hachage. Repli uniquement."""

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dimension
            tokens = text.lower().split()
            for token in tokens:
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimension
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vec[index] += sign
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


class FastEmbedEmbedder(Embedder):
    """paraphrase-multilingual-MiniLM-L12-v2 : 384 dimensions, francais gere.

    Choisi parmi les modeles reellement distribues par fastembed. Un modele
    absent du catalogue provoquerait un repli silencieux sur le hachage, donc
    une recherche semantique inoperante : le nom est verifie au demarrage.

    Ce modele n'utilise pas de prefixe de tache, contrairement a la famille e5.
    """

    MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    dimension = 384

    def __init__(self) -> None:
        from fastembed import TextEmbedding  # import tardif : dependance lourde

        supported = {m["model"] for m in TextEmbedding.list_supported_models()}
        if self.MODEL not in supported:
            raise RuntimeError(
                f"Modele {self.MODEL} absent du catalogue fastembed installe. "
                f"Mettre a jour fastembed ou choisir un modele de la liste."
            )
        self._model = TextEmbedding(model_name=self.MODEL)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


@lru_cache
def get_embedder() -> Embedder:
    if settings.EMBEDDING_BACKEND == "hashing":
        logger.warning("Embeddings en mode hachage : qualite semantique nulle.")
        return HashingEmbedder(settings.EMBEDDING_DIM)

    try:
        embedder = FastEmbedEmbedder()
    except Exception as exc:  # paquet absent ou telechargement impossible
        logger.warning("fastembed indisponible (%s), repli sur le hachage.", exc)
        return HashingEmbedder(settings.EMBEDDING_DIM)

    if embedder.dimension != settings.EMBEDDING_DIM:
        raise RuntimeError(
            f"EMBEDDING_DIM={settings.EMBEDDING_DIM} incompatible avec le modele "
            f"({embedder.dimension}). Ajuster la configuration et rejouer les migrations."
        )
    return embedder
