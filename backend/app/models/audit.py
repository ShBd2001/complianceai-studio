from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
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
from app.models.enums import AuditStatus, FindingStatus, Framework, Severity

if TYPE_CHECKING:
    from app.models.organization import Organization


class Audit(UUIDMixin, TimestampMixin, Base):
    """Une campagne d'audit. C'est l'unite d'historique cote metier."""

    __tablename__ = "audits"
    __table_args__ = (Index("ix_audits_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    framework: Mapped[Framework] = mapped_column(
        Enum(Framework, name="framework", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    status: Mapped[AuditStatus] = mapped_column(
        Enum(AuditStatus, name="audit_status", values_callable=lambda e: [m.value for m in e]),
        default=AuditStatus.DRAFT,
        nullable=False,
    )

    compliance_score: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    organization: Mapped["Organization"] = relationship(back_populates="audits")
    documents: Mapped[list["Document"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan"
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan"
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan"
    )


class Document(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    audit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("audits.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Empreinte d'integrite : detecte toute alteration du fichier stocke.
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)

    audit: Mapped["Audit"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(UUIDMixin, Base):
    """Remplace ChromaDB : index vectoriel dans Postgres via pgvector.

    L'organization_id est duplique ici volontairement : il permet de filtrer
    l'espace vectoriel par locataire directement dans la clause WHERE, ce qui
    rend la fuite inter-organisations structurellement impossible.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_chunks_org", "organization_id"),
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_position"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(Vector(settings.EMBEDDING_DIM), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    document: Mapped["Document"] = relationship(back_populates="chunks")


class Finding(UUIDMixin, TimestampMixin, Base):
    """Une non-conformite detectee, rattachee a un article du referentiel."""

    __tablename__ = "findings"
    __table_args__ = (Index("ix_findings_audit_severity", "audit_id", "severity"),)

    audit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("audits.id", ondelete="CASCADE"), nullable=False
    )
    article_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)

    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="severity", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    status: Mapped[FindingStatus] = mapped_column(
        Enum(FindingStatus, name="finding_status", values_callable=lambda e: [m.value for m in e]),
        default=FindingStatus.OPEN,
        nullable=False,
    )
    # Tracabilite de la generation IA : indispensable pour l'AI Act
    # et pour justifier une recommandation devant un client.
    model_used: Mapped[str | None] = mapped_column(String(80))
    confidence: Mapped[float | None] = mapped_column(Float)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )

    audit: Mapped["Audit"] = relationship(back_populates="findings")


class Report(UUIDMixin, TimestampMixin, Base):
    """Rapport genere, versionne : v1, v2... L'historique des livrables."""

    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("audit_id", "version", name="uq_report_version"),)

    audit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("audits.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    generated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    audit: Mapped["Audit"] = relationship(back_populates="reports")
