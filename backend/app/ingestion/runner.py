"""Orchestrateur d'ingestion et dispositif de veille.

Execution idempotente : si l'empreinte SHA-256 du texte source est inchangee,
rien n'est reecrit. Si elle a change, une nouvelle version est creee et
l'ancienne est conservee, ce qui permet de savoir contre quelle version d'un
referentiel un audit passe a ete evalue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.base import Connector, IngestionResult
from app.ingestion.scoping import classify
from app.models.framework import Framework, FrameworkVersion, Requirement
from app.services.embeddings import get_embedder

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestionReport:
    code: str
    status: str          # "created" | "updated" | "unchanged" | "failed"
    version_label: str | None = None
    requirements: int = 0
    auditable: int = 0
    message: str | None = None


def _upsert_framework(db: Session, result: IngestionResult) -> Framework:
    framework = db.scalar(select(Framework).where(Framework.code == result.code))
    if framework is None:
        framework = Framework(
            code=result.code,
            name=result.name,
            pillar=result.pillar,
            authority=result.authority,
            source_url=result.source_url,
            celex_id=result.celex_id,
            license=result.license,
            is_redistributable=result.is_redistributable,
        )
        db.add(framework)
        db.flush()
    else:
        framework.name = result.name
        framework.source_url = result.source_url
        framework.license = result.license
    return framework


def _embed_requirements(requirements: list[Requirement]) -> None:
    if not requirements:
        return
    embedder = get_embedder()
    # Titre + corps : le titre porte une part importante du sens juridique.
    texts = [f"{r.reference} — {r.title}\n{r.body}"[:8000] for r in requirements]
    for requirement, vector in zip(requirements, embedder.embed(texts), strict=True):
        requirement.embedding = vector


def ingest(db: Session, connector: Connector, *, force: bool = False) -> IngestionReport:
    try:
        result = connector.fetch()
    except Exception as exc:
        logger.exception("Echec de l'ingestion de %s", connector.code)
        return IngestionReport(code=connector.code, status="failed", message=str(exc))

    framework = _upsert_framework(db, result)
    digest = result.sha256

    current = db.scalar(
        select(FrameworkVersion).where(
            FrameworkVersion.framework_id == framework.id,
            FrameworkVersion.is_current.is_(True),
        )
    )

    if current is not None and current.source_sha256 == digest and not force:
        logger.info("%s inchange (empreinte identique).", result.code)
        return IngestionReport(
            code=result.code, status="unchanged", version_label=current.label,
            requirements=len(current.requirements),
            auditable=sum(1 for r in current.requirements if r.is_auditable),
        )

    now = datetime.now(timezone.utc)
    label = result.version_label
    change_note = None

    if current is not None:
        current.is_current = False
        if current.source_sha256 == digest:
            # N'arrive que par --force sur un texte source inchange (la
            # ligne 85 court-circuite deja le cas normal identique+non-force
            # avec le statut "unchanged"). Le message doit le dire tel quel :
            # annoncer une "evolution detectee" alors que l'empreinte est
            # rigoureusement la meme des deux cotes de la fleche induit en
            # erreur quiconque consulte l'historique des versions.
            change_note = (
                f"Reingestion forcee le {now.date().isoformat()} : "
                f"texte source inchange (empreinte {digest[:12]})."
            )
        else:
            change_note = (
                f"Evolution detectee : empreinte {current.source_sha256[:12]} "
                f"-> {digest[:12]} le {now.date().isoformat()}."
            )
        # Deux versions ne peuvent pas partager le meme label. Plusieurs
        # reingestions peuvent survenir le meme jour : on suffixe jusqu'a
        # trouver un libelle libre plutot que de compter sur la seule date.
        existing_labels = {v.label for v in framework.versions}
        if label in existing_labels:
            base = f"{label}+{now.strftime('%Y%m%d')}"
            label = base
            counter = 2
            while label in existing_labels:
                label = f"{base}.{counter}"
                counter += 1

    version = FrameworkVersion(
        framework_id=framework.id,
        label=label,
        effective_date=result.effective_date,
        source_sha256=digest,
        ingested_at=now,
        is_current=True,
        change_note=change_note,
    )
    db.add(version)
    db.flush()

    rows: list[Requirement] = []
    for raw in result.requirements:
        scope = classify(result.code, raw.reference, raw.body)
        rows.append(
            Requirement(
                version_id=version.id,
                reference=raw.reference,
                title=raw.title,
                body=raw.body,
                kind=raw.kind,
                ordering=raw.ordering,
                source_url=raw.source_url,
                is_auditable=scope.auditable,
                audience=scope.audience.value,
            )
        )
    db.add_all(rows)
    db.flush()

    _embed_requirements(rows)
    db.flush()

    auditable = sum(1 for r in rows if r.is_auditable)
    status = "updated" if current is not None else "created"
    logger.info(
        "%s %s : %d exigences dont %d auditables (version %s)",
        result.code, status, len(rows), auditable, label,
    )
    return IngestionReport(
        code=result.code, status=status, version_label=label,
        requirements=len(rows), auditable=auditable, message=change_note,
    )


def _connector_for(code: str, fichier):
    # CSRD est une directive modificative : le texte consolide de la
    # directive comptable qu'elle modifie (2013/34/UE) porte les obligations
    # sous forme d'articles de premier niveau, contrairement au texte brut de
    # la directive CSRD elle-meme ou elles restent imbriquees dans la
    # description des modifications. Voir csrd_consolide.py pour le detail.
    if code == "csrd":
        from app.ingestion.csrd_consolide import CsrdConsolideConnector

        return CsrdConsolideConnector(fichier=fichier)

    from app.ingestion.eurlex import EurLexConnector

    return EurLexConnector(code, fichier=fichier)


def ingest_all(
    db: Session,
    codes: list[str] | None = None,
    *,
    force: bool = False,
    fichier=None,
) -> list[IngestionReport]:
    from app.ingestion.eurlex import SOURCES

    targets = codes or list(SOURCES)
    return [
        ingest(db, _connector_for(code, fichier), force=force)
        for code in targets
    ]
