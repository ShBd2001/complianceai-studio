"""Vérification de citation et revue humaine sur les constats.

Le moteur verifie deja en interne qu'une citation avancee par le modele
existe bien dans les documents deposes (voir _passage_correspondant dans
app/services/audit_engine.py) et applique deja plusieurs regles de prudence
(citation introuvable, verdict indetermine, repli heuristique, confiance
faible). Jusqu'ici, rien de tout cela n'etait stocke ni affiche : un constat
"indetermine" etait indiscernable d'un constat ouvert ordinaire, et
l'utilisatrice n'avait aucun moyen de savoir qu'une citation n'avait pas pu
etre retrouvee.

Revision ID: 0015_finding_verification
Revises: 0014_retrait_tsv
"""

import sqlalchemy as sa

from alembic import op

revision = "0015_finding_verification"
down_revision = "0014_retrait_tsv"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("verdict", sa.String(20), nullable=True))
    op.add_column("findings", sa.Column("citation_verified", sa.Boolean(), nullable=True))
    op.add_column(
        "findings",
        sa.Column(
            "needs_human_review", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("findings", sa.Column("review_reason", sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column("findings", "review_reason")
    op.drop_column("findings", "needs_human_review")
    op.drop_column("findings", "citation_verified")
    op.drop_column("findings", "verdict")
