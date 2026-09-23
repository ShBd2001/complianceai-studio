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
