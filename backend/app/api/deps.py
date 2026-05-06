from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Path, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.enums import OrgRole
from app.models.organization import Membership, Organization
from app.models.user import User

bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Authentification requise.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise _UNAUTHORIZED

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise _UNAUTHORIZED

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise _UNAUTHORIZED from None

    user = db.get(User, user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise _UNAUTHORIZED
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_423_LOCKED, "Compte temporairement verrouille.")
    return user


def get_verified_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_verified:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Adresse e-mail non verifiee."
        )
    return user


class OrgContext:
    """Contexte de locataire resolu pour la requete courante."""

    def __init__(self, organization: Organization, membership: Membership, user: User):
        self.organization = organization
        self.membership = membership
        self.user = user

    @property
    def org_id(self) -> uuid.UUID:
        return self.organization.id

    @property
    def role(self) -> OrgRole:
        return self.membership.role


def get_org_context(
    org_id: uuid.UUID = Path(..., description="Identifiant de l'organisation"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrgContext:
    """Verrou multi-tenant : toute route imbriquee sous /orgs/{org_id} passe ici.

    On renvoie volontairement 404 et non 403 quand l'utilisateur n'est pas
    membre : cela evite de reveler l'existence d'une organisation tierce.
    """
    membership = db.scalar(
        select(Membership).where(
            Membership.organization_id == org_id, Membership.user_id == user.id
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation introuvable.")

    organization = db.get(Organization, org_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation introuvable.")

    return OrgContext(organization, membership, user)


def require_role(minimum: OrgRole) -> Callable[[OrgContext], OrgContext]:
    """Fabrique de dependance RBAC : require_role(OrgRole.ADMIN)."""

    def _checker(ctx: OrgContext = Depends(get_org_context)) -> OrgContext:
        if ctx.role.level < minimum.level:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role insuffisant : '{minimum.value}' requis.",
            )
        return ctx

    return _checker


def get_request(request: Request) -> Request:
    return request
