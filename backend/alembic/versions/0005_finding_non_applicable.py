"""Statut 'non applicable' pour les constats.

Un referentiel contient des obligations conditionnelles. Les articles qui ne
concernent pas l'organisation auditee doivent etre ecartes du score, tout en
restant tracables : l'exclusion doit pouvoir etre verifiee et contestee.

Revision ID: 0005_finding_non_applicable
Revises: 0004_perimetre_auditable
"""
from alembic import op

revision = "0005_finding_non_applicable"
down_revision = "0004_perimetre_auditable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE ne peut pas s'executer dans une transaction
    # avant PostgreSQL 12 ; a partir de 12 c'est permis, mais la valeur n'est
    # utilisable qu'apres validation. IF NOT EXISTS rend la migration rejouable.
    op.execute("ALTER TYPE finding_status ADD VALUE IF NOT EXISTS 'not_applicable'")


def downgrade() -> None:
    # PostgreSQL ne sait pas retirer une valeur d'un type enumere. Le retrait
    # imposerait de recreer le type et de reecrire la colonne ; l'operation
    # n'est pas justifiee ici, la valeur surnumeraire etant inoffensive.
    pass
