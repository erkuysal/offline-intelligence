"""add chunk embeddings

Revision ID: 20260708_0003
Revises: 20260708_0002
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260708_0003"
down_revision: str | Sequence[str] | None = "20260708_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("embedding_json", sa.Text(), nullable=True))
    op.add_column("document_chunks", sa.Column("embedding_model", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "embedding_model")
    op.drop_column("document_chunks", "embedding_json")
