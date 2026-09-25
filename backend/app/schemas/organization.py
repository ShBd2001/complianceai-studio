from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import OrgPlan, OrgRole
from app.services.retention import RETENTION_MIN_JOURS

# Voir app/services/eligibilite.py pour le tableau de correspondance complet.
EntiteNis2 = Literal["essentielle", "importante", "non_concernee"]


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    siren: str | None = Field(default=None, max_length=14)
    sector: str | None = Field(default=None, max_length=80)
    headcount: int | None = Field(default=None, ge=1, le=2_000_000)
    plan: OrgPlan = OrgPlan.ESSENTIEL


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    siren: str | None
    sector: str | None
    headcount: int | None
    plan: OrgPlan
    created_at: datetime
    # Role de l'appelant et effectif total : le frontend en a besoin pour
    # savoir s'il doit proposer "Supprimer" (owner seul) ou "Quitter"
    # (tout le reste) sans requete supplementaire par organisation.
    my_role: OrgRole
    member_count: int
    # NULL = pas de purge automatique. Reserve a l'offre Cabinet, voir
    # app/services/retention.py et PATCH /orgs/{org_id}/retention.
    document_retention_days: int | None = None
    # Profil pour le filtre d'eligibilite -- voir OrganizationProfileUpdate.
    organisme_public: bool | None = None
    donnees_sensibles: bool | None = None
    donnees_penales: bool | None = None
    activite_de_base_traitement: bool | None = None
    suivi_regulier_systematique: bool | None = None
    grande_echelle: bool | None = None
    professionnel_liberal_isole: bool | None = None
    traitement_occasionnel: bool | None = None
    risque_droits_libertes: bool | None = None
    collecte_directe: bool | None = None
    collecte_indirecte: bool | None = None
    entite_nis2: EntiteNis2 | None = None
    entite_financiere_dora: bool | None = None
    ia_fournisseur_haut_risque: bool | None = None
    ia_deployeur_haut_risque: bool | None = None
    ia_utilisee: bool | None = None


class OrganizationProfileUpdate(BaseModel):
    """Chaque champ omis du corps de la requete reste inchange ; envoye avec
    la valeur `null`, il repasse explicitement a "non renseigne". Voir
    PATCH /orgs/{org_id}/profile, qui ne lit que les champs presents
    (`exclude_unset`)."""

    organisme_public: bool | None = None
    donnees_sensibles: bool | None = None
    donnees_penales: bool | None = None
    activite_de_base_traitement: bool | None = None
    suivi_regulier_systematique: bool | None = None
    grande_echelle: bool | None = None
    professionnel_liberal_isole: bool | None = None
    traitement_occasionnel: bool | None = None
    risque_droits_libertes: bool | None = None
    collecte_directe: bool | None = None
    collecte_indirecte: bool | None = None
    entite_nis2: EntiteNis2 | None = None
    entite_financiere_dora: bool | None = None
    ia_fournisseur_haut_risque: bool | None = None
    ia_deployeur_haut_risque: bool | None = None
    ia_utilisee: bool | None = None


class RetentionUpdate(BaseModel):
    document_retention_days: int | None = Field(default=None)

    @field_validator("document_retention_days")
    @classmethod
    def _plancher(cls, value: int | None) -> int | None:
        if value is not None and value < RETENTION_MIN_JOURS:
            raise ValueError(
                f"La retention doit etre desactivee (vide) ou d'au moins "
                f"{RETENTION_MIN_JOURS} jours."
            )
        return value


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
