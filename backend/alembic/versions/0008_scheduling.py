"""Notifications in-app, campagnes d'audit recurrentes et suivi de la veille
reglementaire.

Revision ID: 0008_scheduling
Revises: 0007_dora
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_scheduling"
down_revision: str | None = "0007_dora"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "frameworks",
        sa.Column("watch_checked_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "notifications",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("related_audit_id", sa.UUID(), nullable=True),
        sa.Column("related_framework_code", sa.String(length=30), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["related_audit_id"], ["audits.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_org_created", "notifications", ["organization_id", "created_at"], unique=False
    )

    op.create_table(
        "audit_schedules",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("source_audit_id", sa.UUID(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("title_template", sa.String(length=200), nullable=False),
        sa.Column(
            "framework",
            postgresql.ENUM(
                "rgpd", "nis2", "ai_act", "dora", "csrd", "nist_csf", "anssi",
                name="framework", create_type=False,  # type deja cree en 0002/0003
            ),
            nullable=False,
        ),
        sa.Column(
            "cadence",
            sa.Enum("weekly", "monthly", "quarterly", name="schedule_cadence"),
            nullable=False,
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_audit_id", sa.UUID(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_audit_id"], ["audits.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["last_run_audit_id"], ["audits.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_schedules")
    op.execute("DROP TYPE IF EXISTS schedule_cadence")
    op.drop_index("ix_notifications_org_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_column("frameworks", "watch_checked_at")
