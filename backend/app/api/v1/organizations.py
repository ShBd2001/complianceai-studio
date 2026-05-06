from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import OrgContext, get_current_user, get_org_context, require_role
from app.db.session import get_db
from app.models.activity import ActivityLog
from app.models.enums import OrgRole
from app.models.organization import Membership, Organization
from app.models.user import User
from app.schemas.organization import (
    ActivityLogOut,
    MemberInvite,
    MemberOut,
    OrganizationCreate,
    OrganizationOut,
)
from app.services import activity

router = APIRouter(prefix="/orgs", tags=["Organisations"])


def _slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return (re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower() or "org")[:60]


@router.get("", response_model=list[OrganizationOut])
def list_my_organizations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Organization]:
    return list(
        db.scalars(
            select(Organization)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user.id)
            .order_by(Organization.name)
        )
    )


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Organization:
    slug = _slugify(payload.name)
    if db.scalar(select(Organization.id).where(Organization.slug == slug)) is not None:
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    org = Organization(
        name=payload.name.strip(),
        slug=slug,
        siren=payload.siren,
        sector=payload.sector,
        headcount=payload.headcount,
    )
    db.add(org)
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=OrgRole.OWNER))
    activity.log(
        db, action="org.created", actor_id=user.id, organization_id=org.id,
        entity_type="organization", entity_id=org.id, request=request,
        payload={"name": org.name},
    )
    db.flush()
    return org


@router.get("/{org_id}", response_model=OrganizationOut)
def get_organization(ctx: OrgContext = Depends(get_org_context)) -> Organization:
    return ctx.organization


@router.get("/{org_id}/members", response_model=list[MemberOut])
def list_members(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[MemberOut]:
    rows = db.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.organization_id == ctx.org_id, User.deleted_at.is_(None))
        .order_by(User.full_name)
    ).all()
    return [
        MemberOut(
            user_id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=m.role,
            joined_at=m.created_at,
        )
        for u, m in rows
    ]


@router.post("/{org_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(
    payload: MemberInvite,
    request: Request,
    ctx: OrgContext = Depends(require_role(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
) -> MemberOut:
    if payload.role == OrgRole.OWNER and ctx.role != OrgRole.OWNER:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Seul un owner peut nommer un autre owner."
        )

    target = db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    if target is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Aucun compte pour cette adresse. L'utilisateur doit d'abord s'inscrire.",
        )

    existing = db.scalar(
        select(Membership).where(
            Membership.organization_id == ctx.org_id, Membership.user_id == target.id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cet utilisateur est deja membre.")

    membership = Membership(
        user_id=target.id, organization_id=ctx.org_id, role=payload.role
    )
    db.add(membership)
    activity.log(
        db, action="org.member_added", actor_id=ctx.user.id, organization_id=ctx.org_id,
        entity_type="user", entity_id=target.id, request=request,
        payload={"role": payload.role.value},
    )
    db.flush()
    return MemberOut(
        user_id=target.id,
        email=target.email,
        full_name=target.full_name,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def remove_member(
    user_id: uuid.UUID,
    request: Request,
    ctx: OrgContext = Depends(require_role(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
) -> None:
    membership = db.scalar(
        select(Membership).where(
            Membership.organization_id == ctx.org_id, Membership.user_id == user_id
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membre introuvable.")

    if membership.role == OrgRole.OWNER:
        remaining = db.scalar(
            select(Membership).where(
                Membership.organization_id == ctx.org_id,
                Membership.role == OrgRole.OWNER,
                Membership.user_id != user_id,
            )
        )
        if remaining is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Impossible de retirer le dernier owner de l'organisation.",
            )

    db.delete(membership)
    activity.log(
        db, action="org.member_removed", actor_id=ctx.user.id,
        organization_id=ctx.org_id, entity_type="user", entity_id=user_id,
        request=request,
    )


@router.get("/{org_id}/activity", response_model=list[ActivityLogOut])
def list_activity(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: OrgContext = Depends(require_role(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
) -> list[ActivityLog]:
    """Journal d'audit de l'organisation. Lecture seule, jamais modifiable."""
    return list(
        db.scalars(
            select(ActivityLog)
            .where(ActivityLog.organization_id == ctx.org_id)
            .order_by(ActivityLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
