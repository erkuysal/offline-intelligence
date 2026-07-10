"""add pgvector embeddings

Revision ID: 20260710_0004
Revises: 20260708_0003
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision: str = "20260710_0004"
down_revision: str | Sequence[str] | None = "20260708_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "document_chunks",
        sa.Column("embedding", VECTOR(768), nullable=True),
    )
    op.execute(
        """
        UPDATE document_chunks
        SET embedding = embedding_json::vector
        WHERE embedding_json IS NOT NULL
          AND vector_dims(embedding_json::vector) = 768
        """
    )
    op.execute(
        """
        UPDATE document_chunks
        SET embedding_model = NULL
        WHERE embedding IS NULL
        """
    )
    op.create_index(
        "ix_document_chunks_embedding_hnsw_cosine",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_column("document_chunks", "embedding_json")


def downgrade() -> None:
    op.add_column("document_chunks", sa.Column("embedding_json", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE document_chunks
        SET embedding_json = embedding::text
        WHERE embedding IS NOT NULL
        """
    )
    op.drop_index("ix_document_chunks_embedding_hnsw_cosine", table_name="document_chunks")
    op.drop_column("document_chunks", "embedding")
    op.execute("DROP EXTENSION IF EXISTS vector")
