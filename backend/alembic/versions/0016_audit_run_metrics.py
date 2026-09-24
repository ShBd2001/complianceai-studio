"""Metriques d'execution d'une campagne : mode degrade, appels et jetons.

Jusqu'ici, le seul signal de mode degrade etait le texte libre de
`error_message` : rien n'etait interrogeable, et le jury/l'equipe n'avait
aucun chiffre mesure a presenter sur le cout d'une analyse (nombre d'appels,
jetons, duree). Voir app/services/audit_engine.py::run_audit et
backend/scripts/cout_analyses.py.

Revision ID: 0016_audit_run_metrics
Revises: 0015_finding_verification
"""

import sqlalchemy as sa

from alembic import op

revision = "0016_audit_run_metrics"
down_revision = "0015_finding_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audits",
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("audits", sa.Column("llm_fallbacks", sa.Integer(), nullable=True))
    op.add_column("audits", sa.Column("llm_calls", sa.Integer(), nullable=True))
    op.add_column("audits", sa.Column("llm_prompt_tokens", sa.Integer(), nullable=True))
    op.add_column("audits", sa.Column("llm_completion_tokens", sa.Integer(), nullable=True))
    op.add_column("audits", sa.Column("llm_model", sa.String(80), nullable=True))
    op.add_column("audits", sa.Column("retriever", sa.String(20), nullable=True))
    op.add_column("audits", sa.Column("duration_seconds", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("audits", "duration_seconds")
    op.drop_column("audits", "retriever")
    op.drop_column("audits", "llm_model")
    op.drop_column("audits", "llm_completion_tokens")
    op.drop_column("audits", "llm_prompt_tokens")
    op.drop_column("audits", "llm_calls")
    op.drop_column("audits", "llm_fallbacks")
    op.drop_column("audits", "degraded")
