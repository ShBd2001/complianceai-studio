# NOTE : pas de `from __future__ import annotations` dans ce module.
# slowapi enveloppe les endpoints ; FastAPI resoudrait alors les annotations
# differees dans les globals de slowapi et non les notres.
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import (
    LOGIN_LIMIT,
    PASSWORD_RESET_LIMIT,
    REGISTER_LIMIT,
    RESEND_VERIFICATION_LIMIT,
    limiter,
)
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from app.db.session import get_db
from app.models.enums import ConsentPurpose, OrgRole
from app.models.organization import Membership, Organization
from app.models.user import Consent, OneTimeToken, User, UserSession
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    PasswordChange,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    TokenResponse,
)
from app.services import activity
from app.services import email as email_service

router = APIRouter(prefix="/auth", tags=["Authentification"])

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


# --------------------------------------------------------------------------
# Utilitaires
# --------------------------------------------------------------------------
def _slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return (value or "org")[:60]


def _unique_slug(db: Session, base: str) -> str:
    slug = _slugify(base)
    if db.scalar(select(Organization.id).where(Organization.slug == slug)) is None:
        return slug
    return f"{slug}-{uuid.uuid4().hex[:6]}"


def _issue_refresh(
    db: Session,
    user: User,
    request: Request,
    family_id: uuid.UUID | None = None,
) -> str:
    raw = generate_opaque_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(raw),
            family_id=family_id or uuid.uuid4(),
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
            ip_address=activity.client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:400] or None,
        )
    )
    return raw


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=raw_token,
        max_age=settings.REFRESH_TOKEN_TTL_DAYS * 86400,
        httponly=True,                 # inaccessible au JavaScript -> anti-XSS
        secure=settings.COOKIE_SECURE, # HTTPS uniquement en production
        # "strict" bloquerait totalement le cookie en production : frontend
        # (complianceai-web.onrender.com) et API (complianceai-api-l51c.
        # onrender.com) sont deux sites distincts pour le navigateur (chaque
        # sous-domaine onrender.com est une entree separee de la liste des
        # suffixes publics). "none" est necessaire pour ce cas inter-site
        # reel ; en local (COOKIE_SECURE=false, meme site "localhost" quel
        # que soit le port) "strict" reste la valeur la plus sure.
        samesite="none" if settings.COOKIE_SECURE else "strict",
        path="/api/v1/auth",           # portee minimale
        domain=settings.COOKIE_DOMAIN or None,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path="/api/v1/auth",
        domain=settings.COOKIE_DOMAIN or None,
    )


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, user.is_superuser),
        expires_in=settings.ACCESS_TOKEN_TTL_MIN * 60,
    )


# --------------------------------------------------------------------------
# Inscription
# --------------------------------------------------------------------------
@router.post("/register", response_model=MeResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTER_LIMIT)
def register(
    payload: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Cree l'utilisateur, son organisation et son role OWNER en une transaction."""
    email = payload.email.lower().strip()

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
    )
    org = Organization(
        name=payload.organization_name.strip(),
        slug=_unique_slug(db, payload.organization_name),
    )
    db.add_all([user, org])

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Un compte existe deja pour cette adresse."
        ) from None

    db.add(Membership(user_id=user.id, organization_id=org.id, role=OrgRole.OWNER))
    db.add(
        Consent(
            user_id=user.id,
            purpose=ConsentPurpose.TOS,
            ip_address=activity.client_ip(request),
        )
    )

    # Jeton de verification d'email (a envoyer par e-mail en production).
    raw = generate_opaque_token()
    db.add(
        OneTimeToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            purpose="email_verify",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
    )

    activity.log(
        db,
        action="user.registered",
        actor_id=user.id,
        organization_id=org.id,
        entity_type="user",
        entity_id=user.id,
        request=request,
    )
    db.flush()
    db.refresh(user)

    email_service.send_email(
        to=user.email,
        subject="Vérifiez votre adresse e-mail — ComplianceAI Studio",
        body=(
            f"Bonjour {user.full_name},\n\n"
            "Bienvenue sur ComplianceAI Studio. Confirmez votre adresse e-mail "
            "en ouvrant ce lien :\n\n"
            f"{settings.FRONTEND_URL}/?verify_email={raw}\n\n"
            "Ce lien expire dans 24 heures. Si vous n'etes pas a l'origine de "
            "cette inscription, ignorez ce message.\n"
        ),
    )
    return user


# --------------------------------------------------------------------------
# Connexion
# --------------------------------------------------------------------------
@router.post("/login", response_model=TokenResponse)
@limiter.limit(LOGIN_LIMIT)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    email = payload.email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))

    generic = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Identifiants invalides."
    )

    if user is None:
        # Hachage a vide : maintient un temps de reponse constant et empeche
        # l'enumeration des comptes par mesure de latence.
        hash_password(payload.password)
        raise generic

    now = datetime.now(timezone.utc)
    if user.locked_until and user.locked_until > now:
        raise HTTPException(
            status.HTTP_423_LOCKED,
            "Trop de tentatives. Compte verrouille temporairement.",
        )

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_login_count = 0
        activity.log(
            db, action="auth.login_failed", actor_id=user.id,
            entity_type="user", entity_id=user.id, request=request,
        )
        db.commit()  # le compteur d'echecs doit persister malgre le 401
        raise generic

    if not user.is_active or user.deleted_at is not None:
        raise generic

    # Verifiee apres le mot de passe : la personne vient de prouver qu'elle
    # le connait, ce message ne fuite donc rien a un tiers qui ne l'aurait
    # pas devine.
    if user.email_verified_at is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Adresse e-mail non verifiee. Consultez le lien envoye a "
            f"{user.email} (pensez aux indesirables) avant de vous connecter.",
        )

    # Re-hachage transparent si les parametres Argon2 ont evolue.
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now

    raw_refresh = _issue_refresh(db, user, request)
    _set_refresh_cookie(response, raw_refresh)

    activity.log(
        db, action="auth.login", actor_id=user.id,
        entity_type="user", entity_id=user.id, request=request,
    )
    return _token_response(user)


# --------------------------------------------------------------------------
# Rotation du refresh token
# --------------------------------------------------------------------------
@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    raw = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session absente.")

    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_token(raw))
    )
    if session is None:
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session invalide.")

    now = datetime.now(timezone.utc)

    # Detection de rejeu : un jeton deja revoque qui revient signale un vol.
    # On invalide alors toute la famille de sessions issue de ce login.
    if session.revoked_at is not None:
        db.query(UserSession).filter(
            UserSession.family_id == session.family_id,
            UserSession.revoked_at.is_(None),
        ).update({"revoked_at": now})
        activity.log(
            db, action="auth.refresh_reuse_detected", actor_id=session.user_id,
            entity_type="user_session", entity_id=session.id, request=request,
        )
        db.commit()  # la revocation de la famille doit persister
        _clear_refresh_cookie(response)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Session compromise, reconnexion requise."
        )

    if session.expires_at <= now:
        session.revoked_at = now
        db.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expiree.")

    user = db.get(User, session.user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        session.revoked_at = now
        db.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session invalide.")

    session.revoked_at = now  # rotation : l'ancien jeton meurt immediatement
    new_raw = _issue_refresh(db, user, request, family_id=session.family_id)
    _set_refresh_cookie(response, new_raw)

    return _token_response(user)


# --------------------------------------------------------------------------
# Deconnexion
# --------------------------------------------------------------------------
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> Response:
    raw = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if raw:
        session = db.scalar(
            select(UserSession).where(UserSession.token_hash == hash_token(raw))
        )
        if session and session.revoked_at is None:
            session.revoked_at = datetime.now(timezone.utc)
            activity.log(
                db, action="auth.logout", actor_id=session.user_id, request=request
            )
    _clear_refresh_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def logout_all(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Revoque toutes les sessions : utile apres un soupcon de compromission."""
    db.query(UserSession).filter(
        UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
    ).update({"revoked_at": datetime.now(timezone.utc)})
    activity.log(db, action="auth.logout_all", actor_id=user.id, request=request)
    _clear_refresh_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# Verification d'email
# --------------------------------------------------------------------------
@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def verify_email(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    now = datetime.now(timezone.utc)
    ott = db.scalar(
        select(OneTimeToken).where(
            OneTimeToken.token_hash == hash_token(token),
            OneTimeToken.purpose == "email_verify",
        )
    )
    if ott is None or ott.used_at is not None or ott.expires_at <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Jeton invalide ou expire.")

    user = db.get(User, ott.user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Jeton invalide ou expire.")

    ott.used_at = now
    user.email_verified_at = now
    activity.log(db, action="user.email_verified", actor_id=user.id, request=request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(RESEND_VERIFICATION_LIMIT)
def resend_verification(
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Reponse toujours identique : pas d'enumeration de comptes.

    Sans ceci, un compte cree avant que le SMTP ne soit configure — ou dont
    le premier lien est simplement passe inaperçu — reste bloque a la
    connexion sans aucun recours (voir login() : la connexion exige un
    e-mail verifie).
    """
    user = db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    if user and user.is_active and user.deleted_at is None and user.email_verified_at is None:
        raw = generate_opaque_token()
        db.add(
            OneTimeToken(
                user_id=user.id,
                token_hash=hash_token(raw),
                purpose="email_verify",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
        )
        activity.log(
            db, action="auth.verification_resent", actor_id=user.id, request=request
        )
        email_service.send_email(
            to=user.email,
            subject="Vérifiez votre adresse e-mail — ComplianceAI Studio",
            body=(
                f"Bonjour {user.full_name},\n\n"
                "Confirmez votre adresse e-mail en ouvrant ce lien :\n\n"
                f"{settings.FRONTEND_URL}/?verify_email={raw}\n\n"
                "Ce lien expire dans 24 heures. Si vous n'etes pas a l'origine "
                "de cette demande, ignorez ce message.\n"
            ),
        )
    return {"detail": "Si un compte non verifie existe pour cette adresse, un nouveau lien vient d'etre envoye."}


# --------------------------------------------------------------------------
# Reinitialisation de mot de passe
# --------------------------------------------------------------------------
@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(PASSWORD_RESET_LIMIT)
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Reponse toujours identique : pas d'enumeration de comptes."""
    user = db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    if user and user.is_active and user.deleted_at is None:
        raw = generate_opaque_token()
        db.add(
            OneTimeToken(
                user_id=user.id,
                token_hash=hash_token(raw),
                purpose="password_reset",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        activity.log(
            db, action="auth.password_reset_requested", actor_id=user.id, request=request
        )
        email_service.send_email(
            to=user.email,
            subject="Réinitialisation de votre mot de passe — ComplianceAI Studio",
            body=(
                f"Bonjour {user.full_name},\n\n"
                "Une reinitialisation de mot de passe a ete demandee pour ce "
                "compte. Ouvrez ce lien pour choisir un nouveau mot de passe :\n\n"
                f"{settings.FRONTEND_URL}/?reset_password={raw}\n\n"
                "Ce lien expire dans 1 heure. Si vous n'etes pas a l'origine de "
                "cette demande, ignorez ce message : votre mot de passe reste inchange.\n"
            ),
        )

    return {"detail": "Si un compte existe, un e-mail vient d'etre envoye."}


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def confirm_password_reset(
    payload: PasswordResetConfirm,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    now = datetime.now(timezone.utc)
    ott = db.scalar(
        select(OneTimeToken).where(
            OneTimeToken.token_hash == hash_token(payload.token),
            OneTimeToken.purpose == "password_reset",
        )
    )
    if ott is None or ott.used_at is not None or ott.expires_at <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Jeton invalide ou expire.")

    user = db.get(User, ott.user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Jeton invalide ou expire.")

    ott.used_at = now
    user.password_hash = hash_password(payload.new_password)
    user.failed_login_count = 0
    user.locked_until = None

    # Un changement de mot de passe invalide toutes les sessions existantes.
    db.query(UserSession).filter(
        UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
    ).update({"revoked_at": now})

    activity.log(db, action="auth.password_reset", actor_id=user.id, request=request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def change_password(
    payload: PasswordChange,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mot de passe actuel incorrect.")

    user.password_hash = hash_password(payload.new_password)
    db.query(UserSession).filter(
        UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
    ).update({"revoked_at": datetime.now(timezone.utc)})

    activity.log(db, action="auth.password_changed", actor_id=user.id, request=request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# Profil
# --------------------------------------------------------------------------
@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user
