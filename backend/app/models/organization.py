from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import OrgPlan, OrgRole

if TYPE_CHECKING:
    from app.models.audit import Audit
    from app.models.user import User


class Organization(UUIDMixin, TimestampMixin, Base):
    """Locataire (tenant). Toute donnee metier porte un organization_id."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    siren: Mapped[str | None] = mapped_column(String(14))
    sector: Mapped[str | None] = mapped_column(String(80))
    headcount: Mapped[int | None] = mapped_column(Integer)
    country: Mapped[str] = mapped_column(String(2), default="FR", nullable=False)
    plan: Mapped[OrgPlan] = mapped_column(
        Enum(OrgPlan, name="org_plan", values_callable=lambda e: [m.value for m in e]),
        default=OrgPlan.ESSENTIEL,
        nullable=False,
    )
    # Retention personnalisee des documents deposes (offre Cabinet
    # uniquement, voir app/services/retention.py). NULL = pas de purge
    # automatique -- comportement historique, inchange tant que non defini.
    document_retention_days: Mapped[int | None] = mapped_column(Integer)

    # Profil pour le filtre d'eligibilite (app/services/eligibilite.py,
    # depuis_organisation). NULL = non renseigne, jamais converti en False :
    # une information manquante laisse l'exigence suivre le parcours normal
    # d'evaluation ("a verifier"), elle ne produit jamais une exemption a tort.
    organisme_public: Mapped[bool | None] = mapped_column(Boolean)
    donnees_sensibles: Mapped[bool | None] = mapped_column(Boolean)
    donnees_penales: Mapped[bool | None] = mapped_column(Boolean)
    activite_de_base_traitement: Mapped[bool | None] = mapped_column(Boolean)
    suivi_regulier_systematique: Mapped[bool | None] = mapped_column(Boolean)
    grande_echelle: Mapped[bool | None] = mapped_column(Boolean)
    professionnel_liberal_isole: Mapped[bool | None] = mapped_column(Boolean)
    traitement_occasionnel: Mapped[bool | None] = mapped_column(Boolean)
    risque_droits_libertes: Mapped[bool | None] = mapped_column(Boolean)
    collecte_directe: Mapped[bool | None] = mapped_column(Boolean)
    collecte_indirecte: Mapped[bool | None] = mapped_column(Boolean)

    # Profil NIS2 / DORA / AI Act (voir eligibilite.py pour le tableau de
    # correspondance complet). Meme regle de prudence : NULL n'exempte jamais.
    entite_nis2: Mapped[str | None] = mapped_column(String(20))
    entite_financiere_dora: Mapped[bool | None] = mapped_column(Boolean)
    ia_fournisseur_haut_risque: Mapped[bool | None] = mapped_column(Boolean)
    ia_deployeur_haut_risque: Mapped[bool | None] = mapped_column(Boolean)
    ia_utilisee: Mapped[bool | None] = mapped_column(Boolean)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    audits: Mapped[list["Audit"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class Membership(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_membership"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[OrgRole] = mapped_column(
        Enum(OrgRole, name="org_role", values_callable=lambda e: [m.value for m in e]),
        default=OrgRole.VIEWER,
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="memberships")
    organization: Mapped["Organization"] = relationship(back_populates="memberships")
