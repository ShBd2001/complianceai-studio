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
    """
    framework = db.scalar(select(Framework).where(Framework.code == code))
    if framework is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Referentiel inconnu.")

    source_req, source_ver = aliased(Requirement), aliased(FrameworkVersion)
    target_req, target_ver = aliased(Requirement), aliased(FrameworkVersion)
    target_fw = aliased(Framework)

    rows = db.execute(
        select(Crosswalk, source_req, target_req, target_fw.code)
        .join(source_req, Crosswalk.source_requirement_id == source_req.id)
        .join(source_ver, source_req.version_id == source_ver.id)
        .join(target_req, Crosswalk.target_requirement_id == target_req.id)
        .join(target_ver, target_req.version_id == target_ver.id)
        .join(target_fw, target_ver.framework_id == target_fw.id)
        .where(
            source_ver.framework_id == framework.id,
            source_ver.is_current.is_(True),
            target_ver.is_current.is_(True),
        )
    ).all()

    return [
        CrosswalkOut(
            id=crosswalk.id,
            source_framework=FrameworkCode(code),
            source_reference=source.reference,
            source_title=source.title,
            target_framework=FrameworkCode(target_code),
            target_reference=target.reference,
            target_title=target.title,
            coverage=crosswalk.coverage,
            rationale=crosswalk.rationale,
        )
        for crosswalk, source, target, target_code in rows
    ]
