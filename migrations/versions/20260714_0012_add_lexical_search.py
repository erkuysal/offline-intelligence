"""Add language-neutral lexical search vectors.

Revision ID: 20260714_0012
Revises: 20260714_0011
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260714_0012"
down_revision: str | Sequence[str] | None = "20260714_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEARCH_VECTOR_SQL = (
    "to_tsvector('simple'::regconfig, "
    "translate(coalesce({column}, ''), '-_./:', '     '))"
)


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_SQL.format(column="original_filename"), persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_documents_search_vector_gin",
        "documents",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.add_column(
        "document_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_SQL.format(column="content"), persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_document_chunks_search_vector_gin",
        "document_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_search_vector_gin", table_name="document_chunks")
    op.drop_column("document_chunks", "search_vector")
    op.drop_index("ix_documents_search_vector_gin", table_name="documents")
    op.drop_column("documents", "search_vector")
