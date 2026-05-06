"""Correspondances indicatives entre referentiels (crosswalk).

Ce module ne fait AUCUNE analyse juridique automatisee : les paires ci-dessous
sont des rapprochements couramment cites dans la litterature conformite,
fournis comme point de depart a faire valider par un conseil juridique avant
toute exploitation commerciale ou contractuelle. La table `crosswalks`
existait deja dans le schema (voir app/models/framework.py) mais n'etait
peuplee par rien.

A rejouer manuellement apres toute ingestion qui cree une nouvelle version
d'un referentiel couvert ci-dessous : les correspondances pointent vers des
Requirement precis, resolus sur la version *courante* au moment du seed.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.framework import Crosswalk, Framework, FrameworkVersion, Requirement

logger = logging.getLogger(__name__)

# (code_source, reference_source, code_cible, reference_cible, couverture, justification)
SEED: list[tuple[str, str, str, str, float, str]] = [
    (
        "rgpd", "Article 32", "nis2", "Article 21", 0.6,
        "Mesures techniques et organisationnelles de securite : les deux "
        "articles imposent une gestion des risques et des mesures "
        "proportionnees, sans se recouvrir totalement (le RGPD vise les "
        "donnees personnelles, NIS2 les reseaux et systemes d'information).",
    ),
    (
        "rgpd", "Article 33", "nis2", "Article 23", 0.5,
        "Notification a bref delai a une autorite en cas d'incident ou de "
        "violation : delais et destinataires different, mais la logique "
        "detection-notification est commune aux deux textes.",
    ),
    (
        "rgpd", "Article 30", "dora", "Article 8", 0.35,
        "Le registre des activites de traitement (RGPD) et la cartographie "
        "des actifs informationnels (DORA) partagent l'exigence de savoir "
        "precisement ou et comment les donnees/systemes sont traites, sans "
        "etre le meme document.",
    ),
    (
        "rgpd", "Article 35", "ai_act", "Article 27", 0.45,
        "Analyse d'impact relative a la protection des donnees (RGPD) et "
        "analyse d'impact sur les droits fondamentaux (AI Act) : meme "
        "logique d'evaluation prealable des risques pour les personnes, "
        "perimetres differents.",
    ),
    (
        "rgpd", "Article 28", "dora", "Article 28", 0.4,
        "Encadrement contractuel des sous-traitants (RGPD) et des "
        "prestataires TIC critiques (DORA) : exigences de supervision et de "
        "clauses contractuelles comparables.",
    ),
    (
        "nis2", "Article 21", "dora", "Article 9", 0.5,
        "Mesures de gestion des risques cybersecurite (NIS2) et mesures de "
        "protection et de prevention (DORA) : fort recouvrement sur les "
        "mesures techniques de securite, DORA etant plus prescriptif pour le "
        "secteur financier.",
    ),
]


def _resolve(db: Session, code: str, reference: str) -> Requirement | None:
    return db.scalar(
        select(Requirement)
        .join(FrameworkVersion, Requirement.version_id == FrameworkVersion.id)
        .join(Framework, FrameworkVersion.framework_id == Framework.id)
        .where(
            Framework.code == code,
            FrameworkVersion.is_current.is_(True),
            Requirement.reference == reference,
        )
    )


def seed_crosswalks(db: Session) -> list[str]:
    """Insere/actualise les correspondances de SEED. Idempotent tant que les
    Requirement resolus restent les memes (unique sur la paire d'ids)."""
    messages: list[str] = []
    for src_code, src_ref, tgt_code, tgt_ref, coverage, rationale in SEED:
        source = _resolve(db, src_code, src_ref)
        target = _resolve(db, tgt_code, tgt_ref)
        if source is None or target is None:
            missing = f"{src_code} {src_ref}" if source is None else f"{tgt_code} {tgt_ref}"
            messages.append(f"ignore : {missing} introuvable dans la version courante.")
            logger.warning("Crosswalk ignore : %s introuvable.", missing)
            continue

        existing = db.scalar(
            select(Crosswalk).where(
                Crosswalk.source_requirement_id == source.id,
                Crosswalk.target_requirement_id == target.id,
            )
        )
        if existing is not None:
            existing.coverage = coverage
            existing.rationale = rationale
            messages.append(f"mis a jour : {src_code} {src_ref} -> {tgt_code} {tgt_ref}")
            continue

        db.add(Crosswalk(
            source_requirement_id=source.id,
            target_requirement_id=target.id,
            coverage=coverage,
            rationale=rationale,
        ))
        messages.append(f"cree : {src_code} {src_ref} -> {tgt_code} {tgt_ref}")

    db.flush()
    return messages
