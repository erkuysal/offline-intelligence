"""Add model and token usage to conversation messages.

Revision ID: 20260711_0009
Revises: 20260710_0008
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260711_0009"
down_revision: str | None = "20260710_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversation_messages", sa.Column("model", sa.String(length=100), nullable=True))
    op.add_column("conversation_messages", sa.Column("prompt_tokens", sa.Integer(), nullable=True))
    op.add_column("conversation_messages", sa.Column("completion_tokens", sa.Integer(), nullable=True))
    op.add_column("conversation_messages", sa.Column("total_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation_messages", "total_tokens")
    op.drop_column("conversation_messages", "completion_tokens")
    op.drop_column("conversation_messages", "prompt_tokens")
    op.drop_column("conversation_messages", "model")
