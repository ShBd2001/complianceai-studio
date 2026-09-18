"""Limites d'usage par palier tarifaire (voir la page Tarifs du frontend).

Seuls les deux quotas sans ambiguite sont appliques : nombre de campagnes
creees dans le mois civil en cours, et nombre de membres dans
l'organisation. Voir la note dans OrgPlan (app/models/enums.py) pour ce qui
reste volontairement hors perimetre.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit import Audit
from app.models.enums import OrgPlan
from app.models.organization import Membership

PLAN_LIMITS: dict[OrgPlan, dict[str, int | None]] = {
    OrgPlan.ESSENTIEL: {"campaigns_per_month": 3, "max_members": 1},
    OrgPlan.PRO: {"campaigns_per_month": 15, "max_members": 3},
    OrgPlan.CABINET: {"campaigns_per_month": 100, "max_members": None},
}


def campaigns_created_this_month(db: Session, organization_id: uuid.UUID) -> int:
    start_of_month = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    return (
        db.scalar(
            select(func.count(Audit.id)).where(
                Audit.organization_id == organization_id,
                Audit.created_at >= start_of_month,
            )
        )
        or 0
    )


def campaign_quota_remaining(db: Session, organization) -> int | None:
    """None = illimite. Sinon, nombre de campagnes encore lancables ce mois-ci."""
    limit = PLAN_LIMITS[organization.plan]["campaigns_per_month"]
    if limit is None:
        return None
    used = campaigns_created_this_month(db, organization.id)
    return max(0, limit - used)


def member_quota_remaining(db: Session, organization) -> int | None:
    """None = illimite. Sinon, nombre de personnes encore rattachables."""
    limit = PLAN_LIMITS[organization.plan]["max_members"]
    if limit is None:
        return None
    count = (
        db.scalar(
            select(func.count(Membership.id)).where(
                Membership.organization_id == organization.id
            )
        )
        or 0
    )
    return max(0, limit - count)
