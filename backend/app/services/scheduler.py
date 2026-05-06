"""Boucle de planification in-process : veille reglementaire + campagnes
d'audit recurrentes.

Choix delibere de ne pas ajouter de dependance (pas de Celery/APScheduler/
Redis) : une simple boucle asyncio demarree dans le lifespan de FastAPI,
coherente avec le reste du depot (tout est synchrone, execute en ligne, sans
file de taches). Desactivee par defaut (SCHEDULER_ENABLED=false) : elle
interroge un service externe (EUR-Lex, connu pour throttler les clients
automatises) et peut declencher de vraies depenses de quota LLM sans
supervision humaine — a activer sciemment.

Le travail synchrone (DB, LLM, reseau) tourne dans un thread separe
(asyncio.to_thread) : l'executer directement dans la coroutine gelerait tout
le serveur HTTP pendant la duree du tick (jusqu'a AUDIT_MAX_SECONDS par
campagne recurrente due).

Un verrou consultatif Postgres *transactionnel* (pg_try_advisory_xact_lock,
libere automatiquement au commit/rollback) protege contre l'execution en
double si l'application tourne un jour avec plusieurs workers — pas de risque
de fuite de verrou lie a une connexion du pool, contrairement a la variante
session (pg_advisory_lock/unlock).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.runner import ingest_all
from app.models.audit import Audit
from app.models.enums import Framework as FrameworkCode
from app.models.framework import Framework
from app.services.notifications import notify
from app.services.scheduling import run_due_schedules

logger = logging.getLogger("complianceai.scheduler")

_LOCK_KEY = "complianceai_scheduler"


async def scheduler_loop() -> None:
    logger.info(
        "Planificateur demarre (poll=%ss, veille=%sh).",
        settings.SCHEDULER_POLL_SECONDS, settings.REGULATORY_WATCH_INTERVAL_HOURS,
    )
    while True:
        await asyncio.sleep(settings.SCHEDULER_POLL_SECONDS)
        try:
            await asyncio.to_thread(_run_due_jobs)
        except Exception:
            logger.exception("Tick du planificateur en echec.")


def _run_due_jobs() -> None:
    db = SessionLocal()
    try:
        acquired = db.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"), {"key": _LOCK_KEY}
        ).scalar()
        if not acquired:
            return  # un autre worker tient deja le verrou pour ce tick
        _run_regulatory_watch(db)
        run_due_schedules(db)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Erreur pendant le tick du planificateur.")
    finally:
        db.close()


def _run_regulatory_watch(db: Session) -> None:
    """Reingere (sans forcer) les referentiels dont la derniere verification
    date de plus de REGULATORY_WATCH_INTERVAL_HOURS, et notifie les
    organisations concernees en cas de changement reel du texte source."""
    threshold = datetime.now(timezone.utc) - timedelta(hours=settings.REGULATORY_WATCH_INTERVAL_HOURS)
    due = list(db.scalars(
        select(Framework).where(
            Framework.is_active.is_(True),
            or_(Framework.watch_checked_at.is_(None), Framework.watch_checked_at < threshold),
        )
    ))
    for framework in due:
        try:
            reports = ingest_all(db, codes=[framework.code], force=False)
        except Exception:
            # Une reingestion echouee (EUR-Lex indisponible, throttle...) ne doit
            # pas bloquer le reste des referentiels dus ni redemander une
            # verification au tick suivant immediat.
            logger.exception("Veille reglementaire : echec pour %s.", framework.code)
            framework.watch_checked_at = datetime.now(timezone.utc)
            continue

        framework.watch_checked_at = datetime.now(timezone.utc)

        for report in reports:
            if report.status != "updated":
                continue
            org_ids = db.scalars(
                select(Audit.organization_id)
                .where(Audit.framework == FrameworkCode(framework.code))
                .distinct()
            ).all()
            for org_id in org_ids:
                notify(
                    db,
                    organization_id=org_id,
                    kind="framework.updated",
                    title=f"{framework.code.upper()} a ete mis a jour",
                    body=(
                        f"Le texte source de {framework.name} a change "
                        f"(nouvelle version {report.version_label}). Les campagnes "
                        "utilisant ce referentiel peuvent necessiter une nouvelle analyse."
                    ),
                    related_framework_code=framework.code,
                )
