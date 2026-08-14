from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import OrgRole

# Politique de mot de passe (ANSSI / OWASP) : longueur d'abord, complexite ensuite.
_PWD_MIN = 12
_COMMON = {"password", "motdepasse", "azertyuiop", "123456789012", "qwertyuiop"}


def _validate_password(v: str) -> str:
    if len(v) < _PWD_MIN:
        raise ValueError(f"Le mot de passe doit contenir au moins {_PWD_MIN} caracteres.")
    if len(v) > 128:
        raise ValueError("Le mot de passe ne peut pas depasser 128 caracteres.")
    if v.lower() in _COMMON:
        raise ValueError("Ce mot de passe est trop courant.")
    checks = [
        bool(re.search(r"[a-z]", v)),
        bool(re.search(r"[A-Z]", v)),
        bool(re.search(r"\d", v)),
        bool(re.search(r"[^\w\s]", v)),
    ]
    if sum(checks) < 3:
        raise ValueError(
            "Le mot de passe doit combiner au moins 3 types parmi : minuscules, "
            "majuscules, chiffres, caracteres speciaux."
        )
    return v


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str = Field(min_length=2, max_length=120)
    organization_name: str = Field(min_length=2, max_length=160)
    accept_terms: bool

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return _validate_password(v)

    @field_validator("accept_terms")
    @classmethod
    def must_accept(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Les conditions d'utilisation doivent etre acceptees.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return _validate_password(v)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return _validate_password(v)


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: uuid.UUID
    role: OrgRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
    is_superuser: bool
    email_verified_at: datetime | None
    created_at: datetime


class MeResponse(UserOut):
    memberships: list[MembershipOut] = []
