"""Ajoute le referentiel AI Act et son pilier de gouvernance de l'IA.

Les colonnes `framework` et `pillar` reposent sur des types ENUM PostgreSQL :
etendre l'enumeration Python ne suffit pas, la valeur doit egalement etre
declaree cote base, faute de quoi toute insertion la mentionnant echoue.

`ALTER TYPE ... ADD VALUE` ne peut pas s'executer dans un bloc transactionnel
sur les versions de PostgreSQL anterieures a 12, et reste non reversible : une
valeur ajoutee a un type enumere ne peut pas en etre retiree. La fonction
`downgrade` est donc volontairement inerte, ce qui est sans consequence tant
qu'aucune ligne n'utilise la valeur.

Revision ID: 0006_ai_act
Revises: 0005_finding_non_applicable
"""

from alembic import op

revision = "0006_ai_act"
down_revision = "0005_finding_non_applicable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS rend la migration rejouable sans erreur sur une base ou la
    # valeur aurait deja ete ajoutee manuellement.
    op.execute("ALTER TYPE framework ADD VALUE IF NOT EXISTS 'ai_act'")
    op.execute("ALTER TYPE pillar ADD VALUE IF NOT EXISTS 'ai_governance'")


def downgrade() -> None:
    # PostgreSQL ne permet pas de supprimer une valeur d'un type enumere. Le
    # retrait exigerait de recreer le type et de reecrire toutes les colonnes
    # qui l'utilisent, operation disproportionnee et risquee ici.
    pass
