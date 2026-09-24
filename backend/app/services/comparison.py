"""Comparaison de deux campagnes d'audit sur le meme referentiel (Tache 9).

Compare uniquement les constats dans le perimetre (hors non-applicable) :
une exclusion par le filtre d'eligibilite ou le modele n'est ni une
amelioration ni une aggravation, c'est un hors-sujet pour ce comparatif.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import Audit, Finding
from app.models.enums import FindingStatus, Severity

# Plus le rang est eleve, plus le manquement est grave.
_RANG_SEVERITE = {Severity.INFO: 0, Severity.MINOR: 1, Severity.MAJOR: 2, Severity.CRITICAL: 3}


@dataclass(slots=True)
class ArticleComparison:
    article_ref: str
    title: str
    category: str  # nouveau | resolu | inchange | aggrave | ameliore
    severity_before: Severity | None
    severity_after: Severity | None


def _findings_dans_le_perimetre(db: Session, audit_id) -> dict[str, Finding]:
    rows = db.scalars(
        select(Finding).where(
            Finding.audit_id == audit_id,
            Finding.status != FindingStatus.NOT_APPLICABLE,
        )
    )
    return {f.article_ref: f for f in rows}


def compare(
    db: Session, before: Audit, after: Audit
) -> tuple[float | None, list[ArticleComparison]]:
    """`before` est la campagne de reference, `after` celle comparee. Un
    article present dans les deux voit sa gravite confrontee ; present
    seulement dans `after`, c'est un manquement nouveau ; seulement dans
    `before`, il a ete resolu (plus de constat -> conformite acquise)."""
    findings_avant = _findings_dans_le_perimetre(db, before.id)
    findings_apres = _findings_dans_le_perimetre(db, after.id)

    articles: list[ArticleComparison] = []
    for article_ref in sorted(set(findings_avant) | set(findings_apres)):
        f_avant = findings_avant.get(article_ref)
        f_apres = findings_apres.get(article_ref)
        titre = (f_apres or f_avant).title

        if f_avant is None:
            categorie = "nouveau"
        elif f_apres is None:
            categorie = "resolu"
        else:
            rang_avant = _RANG_SEVERITE[f_avant.severity]
            rang_apres = _RANG_SEVERITE[f_apres.severity]
            if rang_apres > rang_avant:
                categorie = "aggrave"
            elif rang_apres < rang_avant:
                categorie = "ameliore"
            else:
                categorie = "inchange"

        articles.append(
            ArticleComparison(
                article_ref=article_ref, title=titre, category=categorie,
                severity_before=f_avant.severity if f_avant else None,
                severity_after=f_apres.severity if f_apres else None,
            )
        )

    score_delta = (
        after.compliance_score - before.compliance_score
        if after.compliance_score is not None and before.compliance_score is not None
        else None
    )
    return score_delta, articles
