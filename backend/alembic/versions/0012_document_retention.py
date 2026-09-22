"""Retention personnalisee des documents deposes (offre Cabinet).

Ajoute Organization.document_retention_days (nombre de jours avant purge du
contenu d'un document deja analyse -- NULL = pas de purge automatique,
comportement actuel inchange pour tout le monde tant que ce n'est pas
configure) et Document.content_purged_at (date de purge effective, pour
que l'interface explique pourquoi un document n'a plus de contenu relisible
plutot que de laisser croire a un bug).

La purge, une fois programmee, efface le fichier stocke et le texte extrait
indexe (DocumentChunk) -- jamais les constats (Finding) ni le rapport
(Report) deja produits : la valeur probante de l'audit survit a la purge du
document source. Voir app/services/retention.py.

Revision ID: 0012_document_retention
Revises: 0011_org_plan
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_document_retention"
down_revision = "0011_org_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("document_retention_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("content_purged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "content_purged_at")
    op.drop_column("organizations", "document_retention_days")
