"""Fil de notifications in-app d'une organisation. Lecture seule cote API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import OrgContext, get_org_context
from app.db.session import get_db
from app.models.notification import Notification
from app.schemas.notification import NotificationOut

router = APIRouter(prefix="/orgs/{org_id}/notifications", tags=["Notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    limit: int = Query(100, ge=1, le=300),
    offset: int = Query(0, ge=0),
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.organization_id == ctx.org_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
