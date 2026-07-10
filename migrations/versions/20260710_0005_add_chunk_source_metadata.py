"""add chunk source metadata

Revision ID: 20260710_0005
Revises: 20260710_0004
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260710_0005"
down_revision: str | Sequence[str] | None = "20260710_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("source_page", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("source_label", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "source_label")
    op.drop_column("document_chunks", "source_page")
