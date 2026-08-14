"""Ajoute le referentiel DORA et son pilier de resilience operationnelle.

Meme contrainte que la revision precedente : `framework` et `pillar` sont des
types ENUM PostgreSQL, et une valeur absente du type fait echouer toute
insertion qui la mentionne.

`ALTER TYPE ... ADD VALUE` n'est pas reversible : PostgreSQL ne permet pas de
retirer une valeur d'un type enumere. La fonction `downgrade` est donc inerte.

Revision ID: 0007_dora
Revises: 0006_ai_act
"""

from alembic import op

revision = "0007_dora"
down_revision = "0006_ai_act"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE framework ADD VALUE IF NOT EXISTS 'dora'")
    op.execute("ALTER TYPE pillar ADD VALUE IF NOT EXISTS 'operational_resilience'")


def downgrade() -> None:
    # Le retrait exigerait de recreer le type et de reecrire toutes les colonnes
    # qui l'utilisent, operation disproportionnee au regard du gain.
    pass
