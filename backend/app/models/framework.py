"""Referentiels reglementaires : textes sources, exigences, points de controle.

Le texte brut d'un reglement est public. La valeur du produit reside dans sa
transformation en points de controle verifiables et dans les correspondances
entre referentiels.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import Pillar, RequirementKind, Severity

if TYPE_CHECKING:
    pass


class Framework(UUIDMixin, TimestampMixin, Base):
    """Un referentiel : RGPD, NIS2, CSRD, NIST CSF, guide ANSSI..."""

    __tablename__ = "frameworks"

    code: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    pillar: Mapped[Pillar] = mapped_column(
        Enum(Pillar, name="pillar", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    authority: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Tracabilite juridique de la source : indispensable pour un outil de
    # conformite qui redistribue du texte reglementaire.
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    celex_id: Mapped[str | None] = mapped_column(String(20))
    license: Mapped[str] = mapped_column(String(120), nullable=False)
    is_redistributable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Horodatage de la derniere TENTATIVE de verification par la veille
    # reglementaire (mis a jour que le texte ait change ou non) — distinct de
    # FrameworkVersion.ingested_at, qui ne bouge que quand le texte change
    # reellement. Necessaire pour cadencer la veille sans reinterroger
    # EUR-Lex a chaque tick.
    watch_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    versions: Mapped[list["FrameworkVersion"]] = relationship(
        back_populates="framework", cascade="all, delete-orphan"
    )


class FrameworkVersion(UUIDMixin, TimestampMixin, Base):
    """Une version datee d'un referentiel.

    L'empreinte SHA-256 du texte ingere est le coeur du dispositif de veille :
    le job periodique la recalcule et cree une nouvelle version des qu'elle
    diverge.
    """

    __tablename__ = "framework_versions"
    __table_args__ = (UniqueConstraint("framework_id", "label", name="uq_framework_version"),)

    framework_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("frameworks.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text)

    framework: Mapped["Framework"] = relationship(back_populates="versions")
    requirements: Mapped[list["Requirement"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class Requirement(UUIDMixin, TimestampMixin, Base):
    """Une exigence : article, paragraphe ou mesure du referentiel."""

    __tablename__ = "requirements"
    __table_args__ = (
        UniqueConstraint("version_id", "reference", name="uq_requirement_reference"),
        Index("ix_requirements_version", "version_id"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("framework_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE")
    )

    reference: Mapped[str] = mapped_column(String(60), nullable=False)  # "Article 32"
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[RequirementKind] = mapped_column(
        Enum(RequirementKind, name="requirement_kind",
             values_callable=lambda e: [m.value for m in e]),
        default=RequirementKind.ARTICLE,
        nullable=False,
    )
    ordering: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(600))

    # Perimetre d'audit. Les articles adresses aux Etats membres ou aux
    # autorites de controle ne sont pas confrontes aux documents d'un client :
    # ils produiraient du bruit sans valeur. Voir app/ingestion/scoping.py.
    is_auditable: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    audience: Mapped[str] = mapped_column(String(20), default="structural", nullable=False)

    # Le decoupage suit la structure juridique : une exigence = un embedding.
    # Couper a N tokens detruirait l'unite semantique de l'article.
    embedding: Mapped[Any | None] = mapped_column(
        Vector(settings.EMBEDDING_DIM), nullable=True
    )

    version: Mapped["FrameworkVersion"] = relationship(back_populates="requirements")
    control_points: Mapped[list["ControlPoint"]] = relationship(
        back_populates="requirement", cascade="all, delete-orphan"
    )


class ControlPoint(UUIDMixin, TimestampMixin, Base):
    """Question d'audit derivee d'une exigence.

    "Article 30 : le responsable du traitement tient un registre" devient
    "Tenez-vous un registre des activites de traitement a jour ?".
    C'est la couche a valeur ajoutee du produit.
    """

    __tablename__ = "control_points"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_evidence: Mapped[str | None] = mapped_column(Text)
    remediation: Mapped[str | None] = mapped_column(Text)
    default_severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="severity", values_callable=lambda e: [m.value for m in e]),
        default=Severity.MAJOR,
        nullable=False,
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    keywords: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    requirement: Mapped["Requirement"] = relationship(back_populates="control_points")


class Crosswalk(UUIDMixin, TimestampMixin, Base):
    """Correspondance entre deux exigences de referentiels differents.

    Argument commercial direct : auditer RGPD art. 32 couvre une large part de
    NIS2 art. 21. Le client paie une fois, obtient deux conformites partielles.
    """

    __tablename__ = "crosswalks"
    __table_args__ = (
        UniqueConstraint("source_requirement_id", "target_requirement_id", name="uq_crosswalk"),
    )

    source_requirement_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False
    )
    target_requirement_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False
    )
    coverage: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
