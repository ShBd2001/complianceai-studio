"""Activation des extensions PostgreSQL requises.

Revision ID: 0001_extensions
Revises:
"""
from alembic import op

revision = "0001_extensions"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector : index vectoriel pour la recherche semantique (remplace ChromaDB).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # pgcrypto : gen_random_uuid() et primitives de chiffrement cote base.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
