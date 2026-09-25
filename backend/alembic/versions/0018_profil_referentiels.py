"""Profil de l'organisation pour le filtre d'eligibilite NIS2, DORA, AI Act.

Prolonge le profil pose par la migration 0017 (RGPD uniquement) aux trois
autres referentiels fiabilises cette semaine. Voir
app/services/eligibilite.py pour le tableau de correspondance complet et
les regles qui lisent ces colonnes.

Toutes nullable : NULL signifie "non renseigne" et ne doit JAMAIS etre
converti en False/"non_concernee" par le code applicatif -- meme principe
de prudence que la migration 0017.

Revision ID: 0018_profil_referentiels
Revises: 0017_profil_organisation
"""

import sqlalchemy as sa

from alembic import op

revision = "0018_profil_referentiels"
down_revision = "0017_profil_organisation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("entite_nis2", sa.String(20), nullable=True))
    op.add_column(
        "organizations", sa.Column("entite_financiere_dora", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("ia_fournisseur_haut_risque", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("ia_deployeur_haut_risque", sa.Boolean(), nullable=True)
    )
    op.add_column("organizations", sa.Column("ia_utilisee", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "ia_utilisee")
    op.drop_column("organizations", "ia_deployeur_haut_risque")
    op.drop_column("organizations", "ia_fournisseur_haut_risque")
    op.drop_column("organizations", "entite_financiere_dora")
    op.drop_column("organizations", "entite_nis2")
