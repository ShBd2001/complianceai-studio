"""Ajoute Organization.plan (offre tarifaire choisie a l'inscription).

Jusqu'ici, choisir "Essentiel"/"Pro"/"Cabinet" sur la page Tarifs menait au
meme formulaire d'inscription generique, sans que l'offre cliquee ne soit
jamais conservee nulle part. Ce champ la stocke reellement, et sert de base
pour y brancher plus tard de vraies limites (campagnes/utilisateurs/
organisations par palier, voir OrgPlan dans app/models/enums.py) -- aucune
n'est encore appliquee cote serveur a ce stade.

server_default puis retrait : les organisations deja en base (creees avant
l'existence des offres payantes) recoivent 'essentiel', l'offre d'entree,
plutot qu'une valeur arbitraire.

Revision ID: 0011_org_plan
Revises: 0010_masque_csrd
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_org_plan"
down_revision = "0010_masque_csrd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    org_plan = sa.Enum("essentiel", "pro", "cabinet", name="org_plan")
    org_plan.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "organizations",
        sa.Column("plan", org_plan, nullable=False, server_default="essentiel"),
    )
    op.alter_column("organizations", "plan", server_default=None)


def downgrade() -> None:
    op.drop_column("organizations", "plan")
    sa.Enum(name="org_plan").drop(op.get_bind(), checkfirst=True)
