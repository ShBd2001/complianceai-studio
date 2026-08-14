"""Fil de notifications in-app, par organisation.

Contrairement au journal d'activite (ActivityLog), ce n'est pas une piste
d'audit de securite : c'est une file de faits notables ("ce referentiel a
change", "cette campagne planifiee vient de s'executer") destinee a etre lue
par les membres de l'organisation. Pas d'etat "lu/non lu" cote serveur : le
frontend calcule ca localement (voir frontend/index.html), un etat partage et
mutable au niveau de l'org n'a pas la meme semantique qu'un flux append-only.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Notification(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_org_created", "organization_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    related_audit_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("audits.id", ondelete="SET NULL")
    )
    related_framework_code: Mapped[str | None] = mapped_column(String(30))
