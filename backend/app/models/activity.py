from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class ActivityLog(UUIDMixin, TimestampMixin, Base):
    """Journal d'activite en ajout seul (append-only).

    Repond a deux exigences distinctes :
    - RGPD art. 30 : registre des activites de traitement.
    - NIS2 art. 21.2.b : capacite de detection et de suivi des incidents.

    Aucune route d'API ne permet UPDATE ni DELETE sur cette table.
    """

    __tablename__ = "activity_logs"
    __table_args__ = (
        Index("ix_activity_org_created", "organization_id", "created_at"),
        Index("ix_activity_actor_created", "actor_id", "created_at"),
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL")
    )

    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(400))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
