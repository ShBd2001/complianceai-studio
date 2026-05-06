"""
Vérification mécanique des citations produites par le modèle.

Garde-fou central : une citation qui n'existe pas littéralement dans le document
audité est rejetée, et l'élément probant correspondant est réputé non satisfait.
Cette vérification est faite par du code déterministe, jamais par le modèle.

Sans cette étape, l'anti-fabrication n'est qu'une consigne dans un prompt.
Avec elle, c'est une contrainte.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

# Seuil de similarité toléré pour absorber les reformulations mineures
# (ponctuation, élisions, espaces insécables). En dessous, la citation est rejetée.
SEUIL_SIMILARITE = 0.90
# Une citation courte ne peut pas établir qu'une obligation entière est
# satisfaite : le seuil est élevé pour la conformité.
LONGUEUR_MINIMALE = 25
# En revanche, une exclusion ou une dérogation se prouve souvent en peu de
# mots — « tous établis en France », « aucun sous-traitant ». Seuil abaissé,
# la vérification littérale restant entière.
LONGUEUR_MINIMALE_EXCLUSION = 15


def normaliser(texte: str) -> str:
    """Normalisation agressive : casse, accents, ponctuation, espaces."""
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = texte.lower()
    texte = texte.replace("’", "'").replace("‘", "'")
    texte = texte.replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"')
    texte = re.sub(r"[^\w\s']", " ", texte)
    texte = re.sub(r"\s+", " ", texte)
    return texte.strip()


@dataclass(frozen=True)
class ResultatVerification:
    valide: bool
    motif: str
    similarite: float = 0.0
    position: int = -1

    @property
    def rejetee(self) -> bool:
        return not self.valide


def verifier_citation(
    citation: str, document: str, *, longueur_minimale: int = LONGUEUR_MINIMALE
) -> ResultatVerification:
    """
    Vérifie qu'une citation provient bien du document.

    Trois niveaux, du plus strict au plus tolérant :
      1. correspondance exacte après normalisation ;
      2. correspondance approchée par fenêtre glissante (>= SEUIL_SIMILARITE) ;
      3. rejet.
    """
    if not citation or not citation.strip():
        return ResultatVerification(False, "citation vide")

    cit_n = normaliser(citation)
    if len(cit_n) < longueur_minimale:
        return ResultatVerification(
            False,
            f"citation trop courte ({len(cit_n)} caractères normalisés, "
            f"minimum {longueur_minimale}) — ne constitue pas une preuve",
        )

    doc_n = normaliser(document)

    position = doc_n.find(cit_n)
    if position != -1:
        return ResultatVerification(True, "correspondance exacte", 1.0, position)

    meilleure, pos_meilleure = _meilleure_fenetre(cit_n, doc_n)
    if meilleure >= SEUIL_SIMILARITE:
        return ResultatVerification(
            True, f"correspondance approchée ({meilleure:.2f})", meilleure, pos_meilleure
        )

    return ResultatVerification(
        False,
        f"citation absente du document (meilleure similarité {meilleure:.2f} "
        f"< seuil {SEUIL_SIMILARITE}) — preuve rejetée, élément réputé non satisfait",
        meilleure,
    )


def _meilleure_fenetre(aiguille: str, botte: str) -> tuple[float, int]:
    """Recherche approchée par fenêtre glissante, ancrée sur un n-gramme rare."""
    if not aiguille or not botte:
        return 0.0, -1

    taille = len(aiguille)
    ancres = _ancres(aiguille, botte)

    if not ancres:
        # Repli : balayage grossier, pas plus de 400 fenêtres.
        pas = max(1, (len(botte) - taille) // 400) if len(botte) > taille else 1
        ancres = list(range(0, max(1, len(botte) - taille + 1), pas))

    meilleure, position = 0.0, -1
    marge = max(20, taille // 5)
    for depart in ancres:
        debut = max(0, depart - marge)
        fin = min(len(botte), debut + taille + 2 * marge)
        fenetre = botte[debut:fin]
        score = SequenceMatcher(None, aiguille, fenetre).quick_ratio()
        if score < meilleure:
            continue
        score = SequenceMatcher(None, aiguille, fenetre).ratio()
        if score > meilleure:
            meilleure, position = score, debut
        if meilleure >= 0.99:
            break
    return meilleure, position


def _ancres(aiguille: str, botte: str, nb: int = 40) -> list[int]:
    """Positions candidates repérées via des séquences de 12 caractères."""
    positions: list[int] = []
    fenetre = 12
    pas = max(fenetre, len(aiguille) // 8)
    for i in range(0, max(1, len(aiguille) - fenetre), pas):
        motif = aiguille[i : i + fenetre]
        depart = 0
        while len(positions) < nb:
            trouve = botte.find(motif, depart)
            if trouve == -1:
                break
            positions.append(max(0, trouve - i))
            depart = trouve + 1
    return sorted(set(positions))[:nb]


def verifier_lot(citations: list[str], document: str) -> list[ResultatVerification]:
    return [verifier_citation(c, document) for c in citations]


def taux_rejet(resultats: list[ResultatVerification]) -> float:
    """Indicateur de santé : un taux élevé signale un modèle qui fabrique."""
    if not resultats:
        return 0.0
    return sum(1 for r in resultats if r.rejetee) / len(resultats)
