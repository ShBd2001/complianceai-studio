"""
Client LLM.

Deux points importants pour la validation :

  - le cache est explicitement désactivable. Mesurer la reproductibilité avec un
    cache actif ne mesure rien : on relit la même réponse. Le harnais exige
    `cache_actif=False`.
  - la version du modèle est journalisée dans chaque rapport. Un résultat de
    validation sans version de modèle n'est pas reproductible.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MODELE_DEFAUT = "llama-3.3-70b-versatile"


@dataclass
class ClientGroq:
    modele: str = MODELE_DEFAUT
    temperature: float = 0.0
    max_tokens: int = 2048
    cache_actif: bool = True
    tentatives: int = 4
    pause_initiale: float = 1.0
    _cache: dict[str, str] = field(default_factory=dict, repr=False)
    appels: int = field(default=0, repr=False)
    coups_cache: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        try:
            from groq import Groq  # import différé : le harnais tourne sans groq
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "Le paquet `groq` est requis : pip install groq"
            ) from exc
        cle = os.environ.get("GROQ_API_KEY")
        if not cle:
            raise RuntimeError("GROQ_API_KEY absent de l'environnement")
        self._client = Groq(api_key=cle)

    def vider_cache(self) -> None:
        self._cache.clear()
        self.coups_cache = 0

    def _cle(self, systeme: str, utilisateur: str) -> str:
        empreinte = f"{self.modele}|{self.temperature}|{systeme}|{utilisateur}"
        return hashlib.sha256(empreinte.encode()).hexdigest()

    def __call__(self, systeme: str, utilisateur: str) -> str:
        cle = self._cle(systeme, utilisateur)
        if self.cache_actif and cle in self._cache:
            self.coups_cache += 1
            return self._cache[cle]

        pause = self.pause_initiale
        derniere: Exception | None = None

        for tentative in range(self.tentatives):
            try:
                reponse = self._client.chat.completions.create(
                    model=self.modele,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": systeme},
                        {"role": "user", "content": utilisateur},
                    ],
                )
                contenu = reponse.choices[0].message.content or ""
                self.appels += 1
                if self.cache_actif:
                    self._cache[cle] = contenu
                return contenu
            except Exception as exc:  # noqa: BLE001
                derniere = exc
                message = str(exc).lower()
                limite = "rate" in message or "429" in message
                if tentative == self.tentatives - 1:
                    break
                attente = pause * (3 if limite else 1)
                logger.warning(
                    "Groq échec (%s) — nouvelle tentative dans %.1fs", exc, attente
                )
                time.sleep(attente)
                pause *= 2

        raise RuntimeError(f"Groq indisponible après {self.tentatives} tentatives : {derniere}")

    def versions(self) -> dict[str, object]:
        return {
            "modele": self.modele,
            "temperature": self.temperature,
            "cache_actif": self.cache_actif,
            "appels_reels": self.appels,
            "coups_cache": self.coups_cache,
        }
