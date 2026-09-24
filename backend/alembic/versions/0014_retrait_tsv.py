"""Retrait des colonnes tsv (recherche plein texte Postgres) ajoutees par la
migration 0013.

Revenu sur cette approche : la tache de recherche hybride demande de
reprendre a l'identique l'algorithme lexical deja mesure dans
validation/comparaison_retrievers.json (copie depuis
evaluation/evaluateur.py::retriever_lexical, classement en Python) plutot
qu'une methode differente non mesuree independamment (recherche plein texte
Postgres avec configuration 'french'). Voir app/services/rag.py et DA-07
dans docs/architecture.md.

Revision ID: 0014_retrait_tsv
Revises: 0013_recherche_lexicale
"""

from alembic import op

revision = "0014_retrait_tsv"
down_revision = "0013_recherche_lexicale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_requirements_tsv")
    op.execute("ALTER TABLE requirements DROP COLUMN IF EXISTS tsv")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_tsv")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS tsv")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('french', content)) STORED"
    )
    op.execute("CREATE INDEX ix_document_chunks_tsv ON document_chunks USING gin (tsv)")

    op.execute(
        "ALTER TABLE requirements "
        "ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('french', title || ' ' || body)) STORED"
    )
    op.execute("CREATE INDEX ix_requirements_tsv ON requirements USING gin (tsv)")
