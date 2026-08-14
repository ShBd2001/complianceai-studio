"""
Client factice, déterministe, sans appel réseau.

Sert à deux choses :
  - tester la chaîne complète (chunking, extraction, vérification, scoring,
    métriques) en CI sans consommer de quota ni dépendre de Groq ;
  - fournir un plancher de référence : si le vrai modèle fait moins bien que
    cette heuristique lexicale naïve, le problème vient du prompt, pas du LLM.

Il imite le contrat de sortie du modèle, y compris ses erreurs plausibles.
"""

from __future__ import annotations

import json
import re

from evaluation.verificateur import normaliser


class ClientFactice:
    def __init__(self) -> None:
        self.appels = 0

    def vider_cache(self) -> None:  # même interface que ClientGroq
        pass

    def versions(self) -> dict:
        return {"modele": "factice-lexical", "temperature": 0.0, "appels_reels": self.appels}

    def __call__(self, systeme: str, utilisateur: str) -> str:
        self.appels += 1
        document = self._document(utilisateur)

        if "CONDITION D'APPLICABILITÉ DE L'ARTICLE" in utilisateur:
            return json.dumps({"applicable": True, "citation": None,
                               "justification": "applicabilité présumée (client factice)"})

        if "DÉROGATIONS POSSIBLES" in utilisateur:
            return json.dumps({"reference": None, "citation": None,
                               "justification": "aucune dérogation identifiée (client factice)"})

        elements = re.findall(r'cle="([^"]+)"\s*:\s*(.+)', utilisateur)
        sorties = []
        for cle, intitule in elements:
            citation = self._chercher(intitule, document)
            sorties.append({
                "cle": cle,
                "satisfait": citation is not None,
                "citation": citation,
                "commentaire": "extrait trouvé" if citation else "aucune mention trouvée",
            })
        return json.dumps({"elements": sorties}, ensure_ascii=False)

    @staticmethod
    def _document(prompt: str) -> str:
        blocs = prompt.split('"""')
        return blocs[1] if len(blocs) >= 2 else prompt

    @staticmethod
    def _chercher(intitule: str, document: str) -> str | None:
        """Renvoie la première phrase du document couvrant le mieux l'intitulé."""
        mots = {m for m in normaliser(intitule).split() if len(m) > 5}
        if not mots:
            return None

        meilleure, score_max = None, 0
        for phrase in re.split(r"(?<=[.!?])\s+|\n", document):
            propre = phrase.strip()
            if len(propre) < 40:
                continue
            corps = set(normaliser(propre).split())
            score = len(mots & corps)
            if score > score_max:
                meilleure, score_max = propre, score

        # Il faut au moins deux termes distinctifs en commun : sinon, on
        # considère que l'élément n'est pas couvert.
        return meilleure if score_max >= 2 else None
