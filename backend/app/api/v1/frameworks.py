"""Consultation des referentiels ingeres."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.enums import Framework as FrameworkCode
from app.models.framework import Crosswalk, Framework, FrameworkVersion, Requirement
from app.models.user import User
from app.schemas.audit import CrosswalkOut, FrameworkOut, FrameworkVersionOut, RequirementOut

router = APIRouter(prefix="/frameworks", tags=["Referentiels"])


@router.get("", response_model=list[FrameworkOut])
def list_frameworks(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Framework]:
    return list(db.scalars(select(Framework).order_by(Framework.pillar, Framework.code)))


@router.get("/{code}/versions", response_model=list[FrameworkVersionOut])
def list_versions(
    code: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FrameworkVersion]:
    framework = db.scalar(select(Framework).where(Framework.code == code))
    if framework is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Referentiel inconnu.")
    return list(
        db.scalars(
            select(FrameworkVersion)
            .where(FrameworkVersion.framework_id == framework.id)
            .order_by(FrameworkVersion.ingested_at.desc())
        )
    )


@router.get("/{code}/requirements", response_model=list[RequirementOut])
def list_requirements(
    code: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auditable_only: bool = Query(False, description="Ne retourner que le perimetre auditable."),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Requirement]:
    version = db.scalar(
        select(FrameworkVersion)
        .join(Framework, FrameworkVersion.framework_id == Framework.id)
        .where(Framework.code == code, FrameworkVersion.is_current.is_(True))
    )
    if version is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Referentiel '{code}' non ingere. Lancer : "
            f"python -m app.ingestion.cli --only {code}",
        )
    stmt = select(Requirement).where(Requirement.version_id == version.id)
    if auditable_only:
        stmt = stmt.where(Requirement.is_auditable.is_(True))
    return list(
        db.scalars(stmt.order_by(Requirement.ordering).limit(limit).offset(offset))
    )


@router.get("/{code}/crosswalks", response_model=list[CrosswalkOut])
def list_crosswalks(
    code: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CrosswalkOut]:
    """Correspondances indicatives entre ce referentiel et d'autres.

    Indicatives, pas certifiees : voir app/ingestion/crosswalks.py. Les deux
    cotes sont filtres sur la version *courante* de leur referentiel — une
    correspondance dont un cote a ete supersede par une reingestion
    n'apparait plus ici tant que le seed n'a pas ete rejoue.

    Une paire est stockee dans un seul sens (source -> cible), choisi a la
    redaction du seed sans rapport avec ce que l'utilisateur consultera en
    premier. Un referentiel qui n'est jamais "source" dans SEED (ex. DORA,
    AI Act) resterait donc toujours vide sans chercher aussi comme cible.
    Le sens renvoye est ensuite normalise : "source" designe toujours le
    referentiel consulte (`code`), "cible" l'autre — jamais le sens brut de
    stockage — pour que la carte affichee corresponde a ce que le titre de
    la page annonce, quel que soit le sens dans lequel la paire a ete saisie.
    """
    framework = db.scalar(select(Framework).where(Framework.code == code))
    if framework is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Referentiel inconnu.")

    a_req, a_ver = aliased(Requirement), aliased(FrameworkVersion)
    b_req, b_ver = aliased(Requirement), aliased(FrameworkVersion)
    b_fw = aliased(Framework)

    def _query(anchor_col, a_join_col, other_col, b_join_col):
        return db.execute(
            select(Crosswalk, a_req, b_req, b_fw.code)
            .join(a_req, a_join_col == a_req.id)
            .join(a_ver, a_req.version_id == a_ver.id)
            .join(b_req, b_join_col == b_req.id)
            .join(b_ver, b_req.version_id == b_ver.id)
            .join(b_fw, b_ver.framework_id == b_fw.id)
            .where(
                a_ver.framework_id == framework.id,
                a_ver.is_current.is_(True),
                b_ver.is_current.is_(True),
            )
        ).all()

    # Anchor = framework consulte, cote source de la table.
    rows = _query(a_ver, Crosswalk.source_requirement_id, b_ver, Crosswalk.target_requirement_id)
    seen = {crosswalk.id for crosswalk, *_ in rows}
    # Anchor = framework consulte, mais cote cible en base : sens inverse au
    # stockage, deja normalise ici (a_req = ce que l'utilisateur consulte).
    rows += [
        row for row in _query(a_ver, Crosswalk.target_requirement_id, b_ver, Crosswalk.source_requirement_id)
        if row[0].id not in seen
    ]

    return [
        CrosswalkOut(
            id=crosswalk.id,
            source_framework=FrameworkCode(code),
            source_reference=anchor_req.reference,
            source_title=anchor_req.title,
            target_framework=FrameworkCode(other_code),
            target_reference=other_req.reference,
            target_title=other_req.title,
            coverage=crosswalk.coverage,
            rationale=crosswalk.rationale,
        )
        for crosswalk, anchor_req, other_req, other_code in rows
    ]
