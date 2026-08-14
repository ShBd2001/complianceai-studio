from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import OrgRole

if TYPE_CHECKING:
    from app.models.audit import Audit
    from app.models.user import User


class Organization(UUIDMixin, TimestampMixin, Base):
    """Locataire (tenant). Toute donnee metier porte un organization_id."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    siren: Mapped[str | None] = mapped_column(String(14))
    sector: Mapped[str | None] = mapped_column(String(80))
    headcount: Mapped[int | None] = mapped_column(Integer)
    country: Mapped[str] = mapped_column(String(2), default="FR", nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    audits: Mapped[list["Audit"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class Membership(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_membership"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[OrgRole] = mapped_column(
        Enum(OrgRole, name="org_role", values_callable=lambda e: [m.value for m in e]),
        default=OrgRole.VIEWER,
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="memberships")
    organization: Mapped["Organization"] = relationship(back_populates="memberships")
