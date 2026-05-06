"""Perimetre auditable des exigences.

Marque chaque exigence comme auditable ou non chez un client, et enregistre le
destinataire de l'obligation. Les articles adresses aux Etats membres ou aux
autorites de controle sortent ainsi du champ des audits.

Revision ID: 0004_perimetre_auditable
Revises: 0003_referentiels
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_perimetre_auditable"
down_revision = "0003_referentiels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default puis retrait : les lignes deja presentes doivent recevoir
    # une valeur avant que la contrainte NOT NULL s'applique.
    op.add_column(
        "requirements",
        sa.Column("is_auditable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "requirements",
        sa.Column("audience", sa.String(length=20), nullable=False,
                  server_default="structural"),
    )
    op.alter_column("requirements", "is_auditable", server_default=None)
    op.alter_column("requirements", "audience", server_default=None)

    op.create_index(
        "ix_requirements_is_auditable", "requirements", ["is_auditable"], unique=False
    )

    # Les index HNSW ne sont pas geres par l'autogeneration d'Alembic : ils
    # sont crees et supprimes explicitement, jamais deduits.


def downgrade() -> None:
    op.drop_index("ix_requirements_is_auditable", table_name="requirements")
    op.drop_column("requirements", "audience")
    op.drop_column("requirements", "is_auditable")
