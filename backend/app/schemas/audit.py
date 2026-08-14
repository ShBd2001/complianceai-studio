from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.enums import (
    AuditStatus,
    FindingStatus,
    Framework,
    Pillar,
    Severity,
)


# --------------------------------------------------------------------------
# Referentiels
# --------------------------------------------------------------------------
class FrameworkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    pillar: Pillar
    authority: str
    source_url: str
    celex_id: str | None
    license: str
    is_active: bool


class FrameworkVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    effective_date: date | None
    source_sha256: str
    ingested_at: datetime
    is_current: bool
    change_note: str | None


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    title: str
    body: str
    ordering: int
    source_url: str | None
    is_auditable: bool
    audience: str


# --------------------------------------------------------------------------
# Audits
# --------------------------------------------------------------------------
class AuditCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    framework: Framework


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    framework: Framework
    status: AuditStatus
    compliance_score: float | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    article_ref: str
    title: str
    description: str
    recommendation: str | None
    evidence: str | None
    severity: Severity
    status: FindingStatus
    model_used: str | None
    confidence: float | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def kind(self) -> str:
        """Non-conformite, axe d'amelioration, ou exigence hors perimetre.

        Derive de la gravite et du statut plutot que stocke : la regle peut
        evoluer sans migration, et deux constats identiques ne peuvent pas
        diverger.
        """
        from app.services.audit_engine import NON_CONFORMITY_SEVERITIES

        if self.status is FindingStatus.NOT_APPLICABLE:
            return "non_applicable"
        return (
            "non_conformite"
            if self.severity in NON_CONFORMITY_SEVERITIES
            else "amelioration"
        )


class FindingUpdate(BaseModel):
    status: FindingStatus


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    sha256: str
    summary: dict
    created_at: datetime


class AuditRunOut(BaseModel):
    audit_id: uuid.UUID
    status: AuditStatus
    score: float | None
    findings: int
    evaluated: int
    message: str | None = None
    degraded: bool = False
    fallbacks: int = 0
    not_applicable: int = 0


class ScoreHistoryPoint(BaseModel):
    audit_id: uuid.UUID
    title: str
    framework: Framework
    score: float | None
    completed_at: datetime | None


class CrosswalkOut(BaseModel):
    id: uuid.UUID
    source_framework: Framework
    source_reference: str
    source_title: str
    target_framework: Framework
    target_reference: str
    target_title: str
    coverage: float
    rationale: str | None
