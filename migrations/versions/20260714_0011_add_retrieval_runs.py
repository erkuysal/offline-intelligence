"""Add retrieval run diagnostics.

Revision ID: 20260714_0011
Revises: 20260712_0010
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260714_0011"
down_revision: str | Sequence[str] | None = "20260712_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "retrieval_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("request_kind", sa.String(length=30), nullable=False),
        sa.Column("strategy", sa.String(length=50), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("query_sha256", sa.String(length=64), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=True),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("selected_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timings_ms", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("selected_context_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_retrieval_runs_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_runs")),
    )
    op.create_index(
        op.f("ix_retrieval_runs_expires_at"),
        "retrieval_runs",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_retrieval_runs_owner_id"),
        "retrieval_runs",
        ["owner_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_retrieval_runs_owner_id"), table_name="retrieval_runs")
    op.drop_index(op.f("ix_retrieval_runs_expires_at"), table_name="retrieval_runs")
    op.drop_table("retrieval_runs")
