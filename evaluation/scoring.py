"""
Score de conformité — formule documentée.

Un score doit pouvoir être expliqué à un auditeur qui demande « d'où sort le
51,7 ? ». La formule ci-dessous est intégralement traçable : chaque article
apporte des points au numérateur, son poids au dénominateur, et le détail est
restitué dans le rapport.

    score = 100 × Σ(poids_i × crédit_i) / Σ(poids_i)

où :
  - poids_i   = criticité de l'article (1 à 5)
  - crédit_i  = 1.0 si conforme
                crédit partiel si manquement (voir ci-dessous)
                article exclu du calcul si hors périmètre ou indéterminé

Le crédit partiel évite l'effet tout-ou-rien : un organisme dont le registre
existe mais n'est pas à jour n'est pas dans la même situation que celui qui
n'en a aucun. Il est calculé comme la proportion d'éléments bloquants prouvés,
plafonnée à 0,5 — un manquement reste un manquement.

Les articles hors périmètre sont EXCLUS du dénominateur, jamais comptés comme
conformes : un artisan sans DPO obligatoire ne doit pas voir son score gonflé
par une obligation qui ne le concerne pas.
"""

from __future__ import annotations

from typing import Any

from evaluation.schemas import Verdict, VerdictArticle

CREDIT_PARTIEL_MAX = 0.5


def credit(v: VerdictArticle) -> float:
    if v.verdict is Verdict.CONFORME:
        return 1.0
    if v.verdict is not Verdict.MANQUEMENT:
        return 0.0

    bloquants = [p for p in v.preuves if p.bloquant]
    if not bloquants:
        return 0.0
    prouves = sum(1 for p in bloquants if p.retenue)
    return min(CREDIT_PARTIEL_MAX, prouves / len(bloquants))


def calculer_score(verdicts: list[VerdictArticle]) -> tuple[float, dict[str, Any]]:
    retenus = [v for v in verdicts if v.compte_dans_le_score]

    if not retenus:
        return 0.0, {
            "formule": "aucun article dans le périmètre — score non calculable",
            "articles_retenus": 0,
        }

    lignes: list[dict[str, Any]] = []
    numerateur = 0.0
    denominateur = 0.0

    for v in retenus:
        c = credit(v)
        numerateur += v.criticite * c
        denominateur += v.criticite
        lignes.append(
            {
                "article": v.article,
                "verdict": v.verdict.value,
                "poids": v.criticite,
                "credit": round(c, 3),
                "points": round(v.criticite * c, 2),
                "points_max": v.criticite,
            }
        )

    score = 100.0 * numerateur / denominateur

    detail = {
        "formule": "100 × Σ(poids × crédit) / Σ(poids)",
        "numerateur": round(numerateur, 2),
        "denominateur": round(denominateur, 2),
        "articles_retenus": len(retenus),
        "articles_exclus": [
            {"article": v.article, "motif": v.verdict.value}
            for v in verdicts
            if not v.compte_dans_le_score
        ],
        "lignes": sorted(lignes, key=lambda x: x["points_max"] - x["points"], reverse=True),
        "pertes_principales": [
            f"art. {l['article']} : -{l['points_max'] - l['points']:.1f} points"
            for l in sorted(lignes, key=lambda x: x["points_max"] - x["points"], reverse=True)[:5]
            if l["points_max"] - l["points"] > 0
        ],
    }
    return round(score, 1), detail


def niveau(score: float) -> str:
    if score >= 85:
        return "Conformité avancée"
    if score >= 70:
        return "Conformité satisfaisante, écarts à traiter"
    if score >= 50:
        return "Conformité partielle, plan d'action nécessaire"
    if score >= 30:
        return "Conformité insuffisante, risque significatif"
    return "Non-conformité majeure"
