"""Reexecution automatique d'une campagne d'audit sur une cadence.

Une planification clone les pieces de la campagne source dans un nouvel
`Audit` a chaque execution (plutot que de rejouer la campagne source en
place) : le tableau de bord trace un point de trajectoire par audit termine,
et c'est justement l'observation de la derive dans le temps qui motive la
fonctionnalite — rejouer en place ferait bouger un seul point au lieu d'en
accumuler l'historique.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import Audit, Document
from app.models.enums import AuditStatus, ScheduleCadence
from app.models.scheduling import AuditSchedule
from app.services import activity, audit_engine, reports
from app.services.documents import read_document, save_document
from app.services.notifications import notify

logger = logging.getLogger("complianceai.scheduler")

_CADENCE_DAYS = {
    ScheduleCadence.WEEKLY: 7,
    ScheduleCadence.MONTHLY: 30,
    ScheduleCadence.QUARTERLY: 91,
}


def compute_next_run(cadence: ScheduleCadence, from_dt: datetime) -> datetime:
    """Pas fixe, volontairement approximatif (pas de calendrier calendaire
    complet — "environ chaque mois" suffit a l'usage vise)."""
    return from_dt + timedelta(days=_CADENCE_DAYS[cadence])


def run_due_schedules(db: Session) -> None:
    now = datetime.now(timezone.utc)
    due = list(
        db.scalars(
            select(AuditSchedule).where(
                AuditSchedule.is_active.is_(True), AuditSchedule.next_run_at <= now
            )
        )
    )
    for schedule in due:
        try:
            run_schedule(db, schedule)
        except Exception:
            logger.exception("Echec de l'execution de la planification %s.", schedule.id)


def _desactiver(db: Session, schedule: AuditSchedule, raison: str) -> None:
    schedule.is_active = False
    notify(
        db,
        organization_id=schedule.organization_id,
        kind="audit_schedule.disabled",
        title=f"Planification désactivée : {schedule.title_template}",
        body=raison,
    )


def run_schedule(db: Session, schedule: AuditSchedule) -> Audit | None:
    if schedule.source_audit_id is None:
        _desactiver(db, schedule, "La campagne source a été supprimée.")
        return None

    source = db.get(Audit, schedule.source_audit_id)
    if source is None:
        schedule.source_audit_id = None
        _desactiver(db, schedule, "La campagne source a été supprimée.")
        return None

    source_documents = list(
        db.scalars(select(Document).where(Document.audit_id == source.id))
    )

    clone = Audit(
        organization_id=schedule.organization_id,
        created_by_id=schedule.created_by_id,
        title=f"{schedule.title_template} — {date.today().isoformat()}",
        framework=schedule.framework,
    )
    db.add(clone)
    db.flush()

    # Content-addresse (voir services/documents.py) : relire puis reecrire
    # les octets est idempotent, aucune nouvelle primitive de stockage.
    for doc in source_documents:
        content = read_document(doc.storage_key)
        key, digest = save_document(schedule.organization_id, doc.filename, content)
        db.add(Document(
            audit_id=clone.id,
            organization_id=schedule.organization_id,
            uploaded_by_id=doc.uploaded_by_id,
            filename=doc.filename,
            mime_type=doc.mime_type,
            size_bytes=doc.size_bytes,
            sha256=digest,
            storage_key=key,
        ))
    db.flush()

    audit_engine.run_audit(db, clone)
    if clone.status == AuditStatus.COMPLETED:
        reports.generate_report(db, clone, user_id=schedule.created_by_id)

    schedule.last_run_audit_id = clone.id
    schedule.next_run_at = compute_next_run(schedule.cadence, datetime.now(timezone.utc))

    reussite = clone.status == AuditStatus.COMPLETED
    notify(
        db,
        organization_id=schedule.organization_id,
        kind="audit_schedule.completed",
        title=f"Campagne planifiée exécutée : {clone.title}",
        body=(
            f"Score de conformité : {clone.compliance_score}/100."
            if reussite and clone.compliance_score is not None
            else f"Analyse terminée sans score publié : {clone.error_message or 'voir la campagne pour le détail.'}"
            if reussite
            else f"L'exécution a échoué : {clone.error_message or 'raison inconnue.'}"
        ),
        related_audit_id=clone.id,
    )
    activity.log(
        db, action="audit.schedule_executed", actor_id=schedule.created_by_id,
        organization_id=schedule.organization_id, entity_type="audit", entity_id=clone.id,
        payload={"planification": str(schedule.id), "statut": clone.status.value},
    )
    return clone
