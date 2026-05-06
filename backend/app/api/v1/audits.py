"""Cycle de vie d'un audit : creation, depot de documents, execution,
resultats, rapport et historique."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import OrgContext, get_org_context, require_role
from app.core.config import settings
from app.db.session import get_db
from app.models.audit import Audit, Document, Finding, Report
from app.models.enums import AuditStatus, OrgRole
from app.models.scheduling import AuditSchedule
from app.schemas.audit import (
    AuditCreate,
    AuditOut,
    AuditRunOut,
    DocumentOut,
    FindingOut,
    FindingUpdate,
    ReportOut,
    ScoreHistoryPoint,
)
from app.schemas.scheduling import ScheduleCreate, ScheduleOut
from app.services import activity, audit_engine, reports
from app.services.documents import ALLOWED_MIME, read_document, save_document
from app.services.scheduling import compute_next_run

router = APIRouter(prefix="/orgs/{org_id}/audits", tags=["Audits"])


def _get_audit(db: Session, ctx: OrgContext, audit_id: uuid.UUID) -> Audit:
    audit = db.scalar(
        select(Audit).where(Audit.id == audit_id, Audit.organization_id == ctx.org_id)
    )
    if audit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Audit introuvable.")
    return audit


# --------------------------------------------------------------------------
@router.get("", response_model=list[AuditOut])
def list_audits(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[Audit]:
    return list(
        db.scalars(
            select(Audit)
            .where(Audit.organization_id == ctx.org_id)
            .order_by(Audit.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )


@router.post("", response_model=AuditOut, status_code=status.HTTP_201_CREATED)
def create_audit(
    payload: AuditCreate,
    request: Request,
    ctx: OrgContext = Depends(require_role(OrgRole.AUDITOR)),
    db: Session = Depends(get_db),
) -> Audit:
    audit = Audit(
        organization_id=ctx.org_id,
        created_by_id=ctx.user.id,
        title=payload.title.strip(),
        framework=payload.framework,
    )
    db.add(audit)
    db.flush()
    activity.log(
        db, action="audit.created", actor_id=ctx.user.id, organization_id=ctx.org_id,
        entity_type="audit", entity_id=audit.id, request=request,
        payload={"framework": payload.framework.value},
    )
    return audit


@router.get("/history", response_model=list[ScoreHistoryPoint])
def score_history(
    framework: str | None = Query(None),
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[ScoreHistoryPoint]:
    """Evolution du score de conformite : le coeur de la valeur percue.

    Un audit isole donne une photographie ; la serie montre une trajectoire,
    ce qui est ce qu'une direction generale attend reellement.
    """
    stmt = (
        select(Audit)
        .where(
            Audit.organization_id == ctx.org_id,
            Audit.status == AuditStatus.COMPLETED,
        )
        .order_by(Audit.completed_at)
    )
    if framework:
        stmt = stmt.where(Audit.framework == framework)

    return [
        ScoreHistoryPoint(
            audit_id=a.id, title=a.title, framework=a.framework,
            score=a.compliance_score, completed_at=a.completed_at,
        )
        for a in db.scalars(stmt)
    ]


@router.get("/{audit_id}", response_model=AuditOut)
def get_audit(
    audit_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> Audit:
    return _get_audit(db, ctx, audit_id)


@router.delete("/{audit_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_audit(
    audit_id: uuid.UUID,
    request: Request,
    ctx: OrgContext = Depends(require_role(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
) -> None:
    audit = _get_audit(db, ctx, audit_id)
    db.delete(audit)
    activity.log(
        db, action="audit.deleted", actor_id=ctx.user.id, organization_id=ctx.org_id,
        entity_type="audit", entity_id=audit_id, request=request,
    )


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
@router.post(
    "/{audit_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    audit_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    ctx: OrgContext = Depends(require_role(OrgRole.AUDITOR)),
    db: Session = Depends(get_db),
) -> Document:
    audit = _get_audit(db, ctx, audit_id)

    mime = file.content_type or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Type non accepte : {mime}. Formats admis : "
            f"{', '.join(sorted(ALLOWED_MIME))}.",
        )

    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Fichier trop volumineux (maximum {settings.MAX_UPLOAD_MB} Mo).",
        )
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")

    key, digest = save_document(ctx.org_id, file.filename or "document", content)

    document = Document(
        audit_id=audit.id,
        organization_id=ctx.org_id,
        uploaded_by_id=ctx.user.id,
        filename=(file.filename or "document")[:255],
        mime_type=mime,
        size_bytes=len(content),
        sha256=digest,
        storage_key=key,
    )
    db.add(document)
    db.flush()

    activity.log(
        db, action="document.uploaded", actor_id=ctx.user.id, organization_id=ctx.org_id,
        entity_type="document", entity_id=document.id, request=request,
        payload={"filename": document.filename, "sha256": digest},
    )
    return document


@router.get("/{audit_id}/documents", response_model=list[DocumentOut])
def list_documents(
    audit_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[Document]:
    _get_audit(db, ctx, audit_id)
    return list(
        db.scalars(
            select(Document)
            .where(Document.audit_id == audit_id)
            .order_by(Document.created_at)
        )
    )


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------
@router.post("/{audit_id}/run", response_model=AuditRunOut)
def run_audit(
    audit_id: uuid.UUID,
    request: Request,
    max_requirements: int | None = Query(
        None, ge=1, le=200,
        description="Reduit volontairement le perimetre. Par defaut, toutes les "
                    "exigences auditables du referentiel sont evaluees.",
    ),
    ctx: OrgContext = Depends(require_role(OrgRole.AUDITOR)),
    db: Session = Depends(get_db),
) -> AuditRunOut:
    """Execution synchrone sur l'ensemble du perimetre auditable.

    Limite connue et documentee : sur un referentiel large, l'appel HTTP peut
    depasser la minute malgre la parallelisation des appels au modele. Le
    passage a une file de taches en arriere-plan est la premiere evolution
    prevue.
    """
    audit = _get_audit(db, ctx, audit_id)
    if audit.status == AuditStatus.RUNNING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Audit deja en cours d'execution.")

    outcome = audit_engine.run_audit(db, audit, max_requirements=max_requirements)

    activity.log(
        db, action="audit.executed", actor_id=ctx.user.id, organization_id=ctx.org_id,
        entity_type="audit", entity_id=audit.id, request=request,
        payload={"statut": outcome.status.value, "score": outcome.score},
    )
    return AuditRunOut(
        audit_id=outcome.audit_id, status=outcome.status, score=outcome.score,
        findings=outcome.findings, evaluated=outcome.evaluated,
        message=outcome.message, degraded=outcome.degraded,
        fallbacks=outcome.fallbacks, not_applicable=outcome.not_applicable,
    )


@router.get("/{audit_id}/findings", response_model=list[FindingOut])
def list_findings(
    audit_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[Finding]:
    _get_audit(db, ctx, audit_id)
    return list(
        db.scalars(
            select(Finding)
            .where(Finding.audit_id == audit_id)
            .order_by(Finding.severity, Finding.article_ref)
        )
    )


@router.patch("/{audit_id}/findings/{finding_id}", response_model=FindingOut)
def update_finding(
    audit_id: uuid.UUID,
    finding_id: uuid.UUID,
    payload: FindingUpdate,
    request: Request,
    ctx: OrgContext = Depends(require_role(OrgRole.AUDITOR)),
    db: Session = Depends(get_db),
) -> Finding:
    _get_audit(db, ctx, audit_id)
    finding = db.scalar(
        select(Finding).where(Finding.id == finding_id, Finding.audit_id == audit_id)
    )
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Constat introuvable.")

    finding.status = payload.status
    activity.log(
        db, action="finding.status_changed", actor_id=ctx.user.id,
        organization_id=ctx.org_id, entity_type="finding", entity_id=finding.id,
        request=request, payload={"statut": payload.status.value},
    )
    return finding


# --------------------------------------------------------------------------
# Rapports
# --------------------------------------------------------------------------
@router.post("/{audit_id}/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def create_report(
    audit_id: uuid.UUID,
    request: Request,
    ctx: OrgContext = Depends(require_role(OrgRole.AUDITOR)),
    db: Session = Depends(get_db),
) -> Report:
    audit = _get_audit(db, ctx, audit_id)
    if audit.status != AuditStatus.COMPLETED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Le rapport ne peut etre genere que pour un audit termine.",
        )

    report = reports.generate_report(db, audit, user_id=ctx.user.id)
    activity.log(
        db, action="report.generated", actor_id=ctx.user.id, organization_id=ctx.org_id,
        entity_type="report", entity_id=report.id, request=request,
        payload={"version": report.version},
    )
    return report


@router.get("/{audit_id}/reports", response_model=list[ReportOut])
def list_reports(
    audit_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[Report]:
    _get_audit(db, ctx, audit_id)
    return list(
        db.scalars(
            select(Report)
            .where(Report.audit_id == audit_id)
            .order_by(Report.version.desc())
        )
    )


@router.get("/{audit_id}/reports/{version}/download")
def download_report(
    audit_id: uuid.UUID,
    version: int,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> Response:
    _get_audit(db, ctx, audit_id)
    report = db.scalar(
        select(Report).where(Report.audit_id == audit_id, Report.version == version)
    )
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rapport introuvable.")

    content = read_document(report.storage_key)
    return Response(
        content=content,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="rapport-v{version}.html"',
            # Ce document est genere par nous, mais on neutralise malgre tout
            # tout script eventuel issu du contenu client cite en preuve.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )


# --------------------------------------------------------------------------
# Planification (reexecution automatique)
# --------------------------------------------------------------------------
@router.post("/{audit_id}/schedule", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
def create_schedule(
    audit_id: uuid.UUID,
    payload: ScheduleCreate,
    request: Request,
    ctx: OrgContext = Depends(require_role(OrgRole.AUDITOR)),
    db: Session = Depends(get_db),
) -> AuditSchedule:
    """Planifie la reexecution periodique de cette campagne. Une seule
    planification active par campagne source : un second appel met a jour
    la cadence de la planification existante plutot que d'en creer une autre."""
    audit = _get_audit(db, ctx, audit_id)
    if audit.status != AuditStatus.COMPLETED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Seule une campagne terminee peut etre planifiee.",
        )

    schedule = db.scalar(
        select(AuditSchedule).where(AuditSchedule.source_audit_id == audit_id)
    )
    if schedule is None:
        schedule = AuditSchedule(
            organization_id=ctx.org_id,
            source_audit_id=audit.id,
            created_by_id=ctx.user.id,
            title_template=audit.title,
            framework=audit.framework,
            cadence=payload.cadence,
            next_run_at=compute_next_run(payload.cadence, datetime.now(timezone.utc)),
        )
        db.add(schedule)
        action = "audit.schedule_created"
    else:
        schedule.cadence = payload.cadence
        schedule.is_active = True
        schedule.next_run_at = compute_next_run(payload.cadence, datetime.now(timezone.utc))
        action = "audit.schedule_updated"
    db.flush()

    activity.log(
        db, action=action, actor_id=ctx.user.id, organization_id=ctx.org_id,
        entity_type="audit", entity_id=audit.id, request=request,
        payload={"cadence": payload.cadence.value},
    )
    return schedule


@router.get("/{audit_id}/schedule", response_model=ScheduleOut)
def get_schedule(
    audit_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> AuditSchedule:
    _get_audit(db, ctx, audit_id)
    schedule = db.scalar(
        select(AuditSchedule).where(AuditSchedule.source_audit_id == audit_id)
    )
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune planification pour cette campagne.")
    return schedule


@router.delete("/{audit_id}/schedule", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def cancel_schedule(
    audit_id: uuid.UUID,
    request: Request,
    ctx: OrgContext = Depends(require_role(OrgRole.AUDITOR)),
    db: Session = Depends(get_db),
) -> None:
    _get_audit(db, ctx, audit_id)
    schedule = db.scalar(
        select(AuditSchedule).where(AuditSchedule.source_audit_id == audit_id)
    )
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune planification pour cette campagne.")
    schedule.is_active = False
    activity.log(
        db, action="audit.schedule_cancelled", actor_id=ctx.user.id, organization_id=ctx.org_id,
        entity_type="audit", entity_id=audit_id, request=request,
    )
