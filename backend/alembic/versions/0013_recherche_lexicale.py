"""Recherche lexicale (plein texte Postgres) en complement du semantique.

Colonnes generees (STORED, calculees par Postgres a chaque ecriture -- jamais
par l'application, donc toujours a jour meme pour des lignes ecrites avant
cette migration une fois celle-ci rejouee) : `document_chunks.tsv` a partir
de `content`, `requirements.tsv` a partir de `title || ' ' || body`.
Configuration 'french' : gere la flexion (traite/traitement/traites matchent
tous), pas seulement l'egalite de chaine exacte comme un LIKE. Indexees en
GIN pour un `@@` / `ts_rank_cd` rapide.

Mesure sur le corpus de validation (voir validation/comparer_retrievers.py,
comparaison_retrievers.json) : sur des textes reglementaires, le lexical seul
bat le semantique seul sur toutes les metriques -- d'ou son ajout ici en
complement, fusionne au semantique existant plutot que de le remplacer (voir
app/services/rag.py).

Revision ID: 0013_recherche_lexicale
Revises: 0012_document_retention
"""

from alembic import op

revision = "0013_recherche_lexicale"
down_revision = "0012_document_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_requirements_tsv")
    op.execute("ALTER TABLE requirements DROP COLUMN IF EXISTS tsv")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_tsv")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS tsv")
