from __future__ import annotations

import ipaddress
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.activity import ActivityLog

# Champs jamais journalises (minimisation, RGPD art. 5.1.c)
_REDACTED = {"password", "new_password", "current_password", "token", "access_token"}


def _sanitize(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    return {k: ("[REDACTED]" if k in _REDACTED else v) for k, v in payload.items()}


def _valid_ip(value: str | None) -> str | None:
    """La colonne est de type INET : toute valeur non conforme est rejetee par
    PostgreSQL. X-Forwarded-For etant un en-tete client, il est falsifiable :
    on valide systematiquement avant insertion."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    # Render/Railway placent un reverse proxy devant l'application.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return _valid_ip(forwarded.split(",")[0])
    return _valid_ip(request.client.host if request.client else None)


def log(
    db: Session,
    *,
    action: str,
    actor_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    request: Request | None = None,
    payload: dict[str, Any] | None = None,
) -> ActivityLog:
    entry = ActivityLog(
        actor_id=actor_id,
        organization_id=organization_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent")[:400] if request else None),
        payload=_sanitize(payload),
    )
    db.add(entry)
    db.flush()
    return entry
