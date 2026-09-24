from __future__ import annotations

import re
import unicodedata
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import OrgContext, get_current_user, get_org_context, require_role
from app.db.session import get_db
from app.models.activity import ActivityLog
from app.models.enums import OrgPlan, OrgRole
from app.models.organization import Membership, Organization
from app.models.user import User
from app.schemas.organization import (
    ActivityLogOut,
    MemberInvite,
    MemberOut,
    OrganizationCreate,
    OrganizationOut,
    OrganizationProfileUpdate,
    RetentionUpdate,
)
from app.services import activity
from app.services.quotas import PLAN_LIMITS, member_quota_remaining

router = APIRouter(prefix="/orgs", tags=["Organisations"])

# Champs du profil d'eligibilite (Tache 8) : memes noms cote modele, schema
# et route, pour ne construire la liste qu'une seule fois.
PROFIL_CHAMPS = [
    "organisme_public", "donnees_sensibles", "donnees_penales",
    "activite_de_base_traitement", "suivi_regulier_systematique",
    "grande_echelle", "professionnel_liberal_isole", "traitement_occasionnel",
    "risque_droits_libertes", "collecte_directe", "collecte_indirecte",
]


def _slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return (re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower() or "org")[:60]


def _org_out(org: Organization, role: OrgRole, member_count: int) -> OrganizationOut:
    return OrganizationOut(
        id=org.id, name=org.name, slug=org.slug, siren=org.siren,
        sector=org.sector, headcount=org.headcount, plan=org.plan, created_at=org.created_at,
        my_role=role, member_count=member_count,
        document_retention_days=org.document_retention_days,
        **{champ: getattr(org, champ) for champ in PROFIL_CHAMPS},
    )


@router.get("", response_model=list[OrganizationOut])
def list_my_organizations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[OrganizationOut]:
    rows = db.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.name)
    ).all()
    if not rows:
        return []
    counts = dict(
        db.execute(
            select(Membership.organization_id, func.count(Membership.id))
            .where(Membership.organization_id.in_([org.id for org, _ in rows]))
            .group_by(Membership.organization_id)
        ).all()
    )
    return [_org_out(org, role, counts.get(org.id, 1)) for org, role in rows]


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    slug = _slugify(payload.name)
    if db.scalar(select(Organization.id).where(Organization.slug == slug)) is not None:
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    org = Organization(
        name=payload.name.strip(),
        slug=slug,
        siren=payload.siren,
        sector=payload.sector,
        headcount=payload.headcount,
        plan=payload.plan,
    )
    db.add(org)
    try:
        db.flush()
    except IntegrityError:
        # Le pre-controle ci-dessus n'est pas atomique avec cette ecriture :
        # deux creations concurrentes pour le meme nom d'organisation peuvent
        # toutes les deux lire "slug libre" avant que l'une ou l'autre n'ait
        # commite. Sans ce rattrapage, la course se terminait en 500 generique
        # (geree seulement par le handler global) au lieu d'aboutir avec un
        # slug rendu unique — meme correctif que auth.py::register pour la
        # meme cause.
        db.rollback()
        org.slug = f"{slug}-{uuid.uuid4().hex[:6]}"
        db.add(org)
        db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=OrgRole.OWNER))
    activity.log(
        db, action="org.created", actor_id=user.id, organization_id=org.id,
        entity_type="organization", entity_id=org.id, request=request,
        payload={"name": org.name},
    )
    db.flush()
    return _org_out(org, OrgRole.OWNER, 1)


@router.get("/{org_id}", response_model=OrganizationOut)
def get_organization(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    count = db.scalar(
        select(func.count(Membership.id)).where(Membership.organization_id == ctx.org_id)
    )
    return _org_out(ctx.organization, ctx.role, count)


@router.patch("/{org_id}/retention", response_model=OrganizationOut)
def update_retention(
    payload: RetentionUpdate,
    request: Request,
    ctx: OrgContext = Depends(require_role(OrgRole.OWNER)),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    """Retention personnalisee des documents deposes -- reservee a l'offre
    Cabinet (voir app/services/retention.py). Le plancher de jours est
    valide par le schema RetentionUpdate ; ici on ne verifie que le plan."""
    if ctx.organization.plan != OrgPlan.CABINET:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "La retention personnalisee des documents est reservee a l'offre Cabinet.",
        )

    ctx.organization.document_retention_days = payload.document_retention_days
    activity.log(
        db, action="org.retention_updated", actor_id=ctx.user.id, organization_id=ctx.org_id,
        entity_type="organization", entity_id=ctx.org_id, request=request,
        payload={"document_retention_days": payload.document_retention_days},
    )
    db.flush()
    count = db.scalar(
        select(func.count(Membership.id)).where(Membership.organization_id == ctx.org_id)
    )
    return _org_out(ctx.organization, ctx.role, count)


@router.patch("/{org_id}/profile", response_model=OrganizationOut)
def update_profile(
    payload: OrganizationProfileUpdate,
    request: Request,
    ctx: OrgContext = Depends(require_role(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    """Profil de l'organisation pour le filtre d'eligibilite (Tache 8, voir
    app/services/eligibilite.py). Seuls les champs presents dans le corps de
    la requete sont modifies (`exclude_unset`) : omettre un champ le laisse
    inchange, l'envoyer a `null` le repasse explicitement a "non renseigne"."""
    changements = payload.model_dump(exclude_unset=True)
    for champ, valeur in changements.items():
        setattr(ctx.organization, champ, valeur)

    if changements:
        activity.log(
            db, action="organization.profile_updated", actor_id=ctx.user.id,
            organization_id=ctx.org_id, entity_type="organization",
            entity_id=ctx.org_id, request=request, payload=changements,
        )
    db.flush()
    count = db.scalar(
        select(func.count(Membership.id)).where(Membership.organization_id == ctx.org_id)
    )
    return _org_out(ctx.organization, ctx.role, count)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_organization(
    request: Request,
    ctx: OrgContext = Depends(require_role(OrgRole.OWNER)),
    db: Session = Depends(get_db),
) -> None:
    """Supprime l'organisation et tout ce qui lui appartient (campagnes,
    pieces, rapports, planifications...) — irreversible, jamais de retour
    arriere possible.

    C'est aussi l'issue de secours d'une suppression de compte (art. 17,
    voir privacy.py::delete_my_account) : un owner ne peut pas supprimer son
    compte tant qu'il possede une organisation, et jusqu'ici rien ne
    permettait de la supprimer non plus — impasse pour tout le monde.

    Reserve au cas ou l'organisation n'a plus qu'un seul membre : la
    supprimer couperait sinon l'acces d'autres personnes sans les prevenir.
    Elles doivent d'abord etre retirees (page Equipe).
    """
    autre_membre = db.scalar(
        select(Membership.id).where(
            Membership.organization_id == ctx.org_id, Membership.user_id != ctx.user.id
        )
    )
    if autre_membre is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "D'autres personnes ont encore acces a cette organisation. "
            "Retirez-les d'abord (page Equipe) avant de la supprimer.",
        )

    activity.log(
        db, action="org.deleted", actor_id=ctx.user.id, organization_id=ctx.org_id,
        entity_type="organization", entity_id=ctx.org_id, request=request,
        payload={"name": ctx.organization.name},
    )
    db.flush()
    db.delete(ctx.organization)


@router.get("/{org_id}/members", response_model=list[MemberOut])
def list_members(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[MemberOut]:
    rows = db.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.organization_id == ctx.org_id, User.deleted_at.is_(None))
        .order_by(User.full_name)
    ).all()
    return [
        MemberOut(
            user_id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=m.role,
            joined_at=m.created_at,
        )
        for u, m in rows
    ]


@router.post("/{org_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(
    payload: MemberInvite,
    request: Request,
    ctx: OrgContext = Depends(require_role(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
) -> MemberOut:
    if payload.role == OrgRole.OWNER and ctx.role != OrgRole.OWNER:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Seul un owner peut nommer un autre owner."
        )

    if member_quota_remaining(db, ctx.organization) == 0:
        limit = PLAN_LIMITS[ctx.organization.plan]["max_members"]
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Quota d'utilisateurs atteint ({limit} sur l'offre "
            f"{ctx.organization.plan.value.capitalize()}). Passez a une offre "
            "superieure pour rattacher davantage de personnes.",
        )

    target = db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    if target is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Aucun compte pour cette adresse. L'utilisateur doit d'abord s'inscrire.",
        )

    existing = db.scalar(
        select(Membership).where(
            Membership.organization_id == ctx.org_id, Membership.user_id == target.id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cet utilisateur est deja membre.")

    membership = Membership(
        user_id=target.id, organization_id=ctx.org_id, role=payload.role
    )
    db.add(membership)
    activity.log(
        db, action="org.member_added", actor_id=ctx.user.id, organization_id=ctx.org_id,
        entity_type="user", entity_id=target.id, request=request,
        payload={"role": payload.role.value},
    )
    db.flush()
    return MemberOut(
        user_id=target.id,
        email=target.email,
        full_name=target.full_name,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def remove_member(
    user_id: uuid.UUID,
    request: Request,
    ctx: OrgContext = Depends(require_role(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
) -> None:
    membership = db.scalar(
        select(Membership).where(
            Membership.organization_id == ctx.org_id, Membership.user_id == user_id
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membre introuvable.")

    if membership.role == OrgRole.OWNER:
        # Un admin (niveau inferieur) ne doit pas pouvoir evincer un owner :
        # add_member impose deja cette regle a la nomination (seul un owner
        # peut nommer un owner), mais le retrait n'avait pas son pendant —
        # un admin pouvait retirer un owner unilateralement, y compris sans
        # son consentement. Un owner qui se retire lui-meme reste autorise :
        # ctx.role vaut alors OWNER, cette condition ne le bloque pas.
        if ctx.role != OrgRole.OWNER:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Seul un owner peut retirer un autre owner."
            )
        remaining = db.scalar(
            select(Membership).where(
                Membership.organization_id == ctx.org_id,
                Membership.role == OrgRole.OWNER,
                Membership.user_id != user_id,
            )
        )
        if remaining is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Impossible de retirer le dernier owner de l'organisation.",
            )

    db.delete(membership)
    activity.log(
        db, action="org.member_removed", actor_id=ctx.user.id,
        organization_id=ctx.org_id, entity_type="user", entity_id=user_id,
        request=request,
    )


@router.get("/{org_id}/activity", response_model=list[ActivityLogOut])
def list_activity(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: OrgContext = Depends(require_role(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
) -> list[ActivityLog]:
    """Journal d'audit de l'organisation. Lecture seule, jamais modifiable."""
    return list(
        db.scalars(
            select(ActivityLog)
            .where(ActivityLog.organization_id == ctx.org_id)
            .order_by(ActivityLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
