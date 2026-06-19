from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import OrgRole


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    siren: str | None = Field(default=None, max_length=14)
    sector: str | None = Field(default=None, max_length=80)
    headcount: int | None = Field(default=None, ge=1, le=2_000_000)


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    siren: str | None
    sector: str | None
    headcount: int | None
    created_at: datetime
    # Role de l'appelant et effectif total : le frontend en a besoin pour
    # savoir s'il doit proposer "Supprimer" (owner seul) ou "Quitter"
    # (tout le reste) sans requete supplementaire par organisation.
    my_role: OrgRole
    member_count: int


class MemberInvite(BaseModel):
    email: EmailStr
    role: OrgRole = OrgRole.VIEWER


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    full_name: str
    role: OrgRole
    joined_at: datetime


class ActivityLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    ip_address: str | None
    created_at: datetime

    @field_validator("ip_address", mode="before")
    @classmethod
    def _ip_to_str(cls, value: object) -> str | None:
        return str(value) if value is not None else None
