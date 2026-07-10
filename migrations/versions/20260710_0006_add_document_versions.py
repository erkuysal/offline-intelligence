"""add document versions

Revision ID: 20260710_0006
Revises: 20260710_0005
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260710_0006"
down_revision: str | Sequence[str] | None = "20260710_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("version_number", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_versions_document_id_version_number"),
        sa.UniqueConstraint("storage_path", name=op.f("uq_document_versions_storage_path")),
    )
    op.create_index(op.f("ix_document_versions_document_id"), "document_versions", ["document_id"], unique=False)
    op.execute(
        """
        INSERT INTO document_versions (
            document_id,
            version_number,
            original_filename,
            content_type,
            size_bytes,
            storage_path,
            checksum_sha256,
            created_at,
            updated_at
        )
        SELECT
            id,
            1,
            original_filename,
            content_type,
            size_bytes,
            storage_path,
            checksum_sha256,
            created_at,
            updated_at
        FROM documents
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_versions_document_id"), table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_column("documents", "version_number")
