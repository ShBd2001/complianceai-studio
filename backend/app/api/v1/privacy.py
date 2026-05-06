"""Droits des personnes concernees (RGPD chapitre III).

Ces routes sont ce qui distingue un outil de conformite credible d'une demo :
l'outil applique a lui-meme les exigences qu'il audite chez ses clients.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.enums import OrgRole
from app.models.organization import Membership
from app.models.user import Consent, User, UserSession
from app.services import activity

router = APIRouter(prefix="/privacy", tags=["Donnees personnelles"])


@router.get("/export")
def export_my_data(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Droit a la portabilite (art. 20) : export structure et lisible."""
    sessions = db.scalars(
        select(UserSession).where(UserSession.user_id == user.id)
    ).all()
    memberships = db.scalars(
        select(Membership).where(Membership.user_id == user.id)
    ).all()
    consents = db.scalars(select(Consent).where(Consent.user_id == user.id)).all()

    activity.log(db, action="privacy.data_exported", actor_id=user.id, request=request)

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "identite": {
            "id": str(user.id),
            "email": user.email,
            "nom_complet": user.full_name,
            "cree_le": user.created_at.isoformat(),
            "email_verifie_le": user.email_verified_at.isoformat()
            if user.email_verified_at
            else None,
            "derniere_connexion": user.last_login_at.isoformat()
            if user.last_login_at
            else None,
        },
        "organisations": [
            {"organization_id": str(m.organization_id), "role": m.role.value,
             "depuis": m.created_at.isoformat()}
            for m in memberships
        ],
        "consentements": [
            {"finalite": c.purpose.value, "accorde_le": c.granted_at.isoformat(),
             "retire_le": c.revoked_at.isoformat() if c.revoked_at else None,
             "version_politique": c.policy_version}
            for c in consents
        ],
        "sessions": [
            {"cree_le": s.created_at.isoformat(), "expire_le": s.expires_at.isoformat(),
             # La colonne est de type INET : psycopg la desserialise en objet
             # ipaddress.IPv4Address/IPv6Address, non serialisable tel quel
             # (voir le meme correctif applique a ActivityLogOut).
             "ip": str(s.ip_address) if s.ip_address is not None else None,
             "navigateur": s.user_agent,
             "revoquee": s.revoked_at is not None}
            for s in sessions
        ],
    }


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_my_account(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Droit a l'effacement (art. 17).

    Anonymisation immediate plutot que DELETE brutal : les journaux d'audit
    doivent survivre (obligation legale de conservation, art. 17.3.b), mais
    ils ne doivent plus etre rattachables a une personne identifiee.
    """
    blocking = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id, Membership.role == OrgRole.OWNER
        )
    )
    if blocking is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Vous etes owner d'une organisation. Transferez la propriete ou "
            "supprimez l'organisation avant de supprimer votre compte.",
        )

    now = datetime.now(timezone.utc)
    anon = uuid.uuid4().hex[:12]

    user.email = f"deleted-{anon}@anonymized.local"
    user.full_name = "Utilisateur supprime"
    user.password_hash = "!"           # aucun hash valide -> connexion impossible
    user.is_active = False
    user.deleted_at = now

    db.query(UserSession).filter(
        UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
    ).update({"revoked_at": now})

    activity.log(db, action="privacy.account_deleted", actor_id=None, request=request)
