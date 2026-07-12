"""Add passage snapshots to conversation sources.

Revision ID: 20260712_0010
Revises: 20260711_0009
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260712_0010"
down_revision: str | Sequence[str] | None = "20260711_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversation_sources", sa.Column("content", sa.Text(), nullable=True))
    op.add_column("conversation_sources", sa.Column("char_start", sa.Integer(), nullable=True))
    op.add_column("conversation_sources", sa.Column("char_end", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation_sources", "char_end")
    op.drop_column("conversation_sources", "char_start")
    op.drop_column("conversation_sources", "content")
