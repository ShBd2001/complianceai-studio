"""Primitives cryptographiques : hachage, JWT, jetons opaques.

Choix documentes (ref. CC1.2) :
- Argon2id pour les mots de passe : recommandation OWASP 2024, resistant au
  materiel dedie (GPU/ASIC) la ou bcrypt ne l'est que partiellement.
- Access token JWT court (15 min), non revocable mais a faible fenetre.
- Refresh token opaque (aleatoire 256 bits), stocke HACHE en base et
  revocable individuellement : un dump de la table ne permet pas de rejouer
  une session.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

TokenPurpose = Literal["email_verify", "password_reset"]


# --------------------------------------------------------------------------
# Mots de passe
# --------------------------------------------------------------------------
def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, plain)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


# --------------------------------------------------------------------------
# Access token (JWT)
# --------------------------------------------------------------------------
def create_access_token(user_id: uuid.UUID, is_superuser: bool = False) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sup": is_superuser,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MIN)).timestamp()),
        "typ": "access",
        "jti": secrets.token_urlsafe(8),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    return payload


# --------------------------------------------------------------------------
# "Se connecter avec Google" (OpenID Connect)
# --------------------------------------------------------------------------
# Cree paresseusement : instancier PyJWKClient ne fait aucun appel reseau
# (le jeu de cles JWKS n'est recupere, puis mis en cache, qu'au premier
# jeton a verifier) -- mais un module-level ferait quand meme deviner a la
# lecture qu'un import de ce fichier parle au reseau, ce qui n'est vrai
# nulle part ailleurs ici.
_google_jwks_client: "jwt.PyJWKClient | None" = None


def _get_google_jwks_client() -> "jwt.PyJWKClient":
    global _google_jwks_client
    if _google_jwks_client is None:
        _google_jwks_client = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs")
    return _google_jwks_client


def decode_google_id_token(token: str) -> dict[str, Any] | None:
    """Verifie un jeton d'identite emis par Google (signature, audience,
    emetteur, expiration) et renvoie ses claims, ou None s'il est invalide.

    Ne verifie PAS que l'adresse est confirmee (claim `email_verified`) :
    laisse au point d'appel, qui decide quoi faire de cette information.
    """
    if not settings.GOOGLE_CLIENT_ID:
        return None
    try:
        signing_key = _get_google_jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.GOOGLE_CLIENT_ID,
            issuer=["accounts.google.com", "https://accounts.google.com"],
        )
    except jwt.PyJWTError:
        return None


# --------------------------------------------------------------------------
# Jetons opaques (refresh, verification email, reset password)
# --------------------------------------------------------------------------
def generate_opaque_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """SHA-256 suffit ici : l'entropie du jeton est de 256 bits, il n'y a pas
    d'attaque par dictionnaire possible contrairement a un mot de passe."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)
