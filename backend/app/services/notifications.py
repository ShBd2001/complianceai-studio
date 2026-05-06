from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.organization import Membership
from app.models.user import User
from app.services import email as email_service


def notify(
    db: Session,
    *,
    organization_id: uuid.UUID,
    kind: str,
    title: str,
    body: str,
    related_audit_id: uuid.UUID | None = None,
    related_framework_code: str | None = None,
    notify_by_email: bool = True,
) -> Notification:
    entry = Notification(
        organization_id=organization_id,
        kind=kind,
        title=title,
        body=body,
        related_audit_id=related_audit_id,
        related_framework_code=related_framework_code,
    )
    db.add(entry)
    db.flush()

    if notify_by_email:
        _email_members(db, organization_id, title, body)

    return entry


def _email_members(db: Session, organization_id: uuid.UUID, title: str, body: str) -> None:
    addresses = db.scalars(
        select(User.email)
        .join(Membership, Membership.user_id == User.id)
        .where(
            Membership.organization_id == organization_id,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    ).all()
    for address in addresses:
        email_service.send_email(
            to=address,
            subject=f"[ComplianceAI Studio] {title}",
            body=(
                f"{body}\n\n"
                "— Vous recevez cet e-mail car vous êtes membre de cette "
                "organisation sur ComplianceAI Studio. Retrouvez l'historique "
                "complet dans Notifications, dans l'application."
            ),
        )
