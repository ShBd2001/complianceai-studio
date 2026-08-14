"""Planification de la reexecution automatique d'une campagne d'audit."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import Framework, ScheduleCadence


class AuditSchedule(UUIDMixin, TimestampMixin, Base):
    """Rejoue periodiquement une campagne terminee sur les memes pieces, avec
    le referentiel a jour — une planification par campagne source."""

    __tablename__ = "audit_schedules"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL (pas CASCADE) : la suppression de la campagne source ne doit
    # pas supprimer silencieusement la planification, elle doit la
    # desactiver explicitement au prochain tick (voir services/scheduling.py).
    source_audit_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("audits.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    title_template: Mapped[str] = mapped_column(String(200), nullable=False)
    framework: Mapped[Framework] = mapped_column(
        Enum(Framework, name="framework", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    cadence: Mapped[ScheduleCadence] = mapped_column(
        Enum(ScheduleCadence, name="schedule_cadence", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_audit_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("audits.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
