from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import text

from app.db.session import engine


ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
SOURCE_REVISION = "20260710_0008"
TARGET_REVISION = "20260714_0013"


def alembic(*arguments: str) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ROOT / "alembic.ini"),
            *arguments,
        ],
        cwd=API_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        check=True,
        text=True,
    )


def test_representative_persisted_data_survives_forward_migrations() -> None:
    engine.dispose()
    try:
        alembic("downgrade", SOURCE_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE conversation_sources, conversation_messages, "
                    "conversations, document_permissions, document_versions, "
                    "document_chunks, documents, user_roles, users, roles "
                    "RESTART IDENTITY CASCADE"
                )
            )
            user_id = connection.execute(
                text(
                    "INSERT INTO users (email, password_hash) "
                    "VALUES ('upgrade-proof@example.test', 'fixture-hash') "
                    "RETURNING id"
                )
            ).scalar_one()
            document_id = connection.execute(
                text(
                    "INSERT INTO documents "
                    "(owner_id, original_filename, content_type, size_bytes, "
                    "storage_path, checksum_sha256, status) "
                    "VALUES (:owner_id, 'upgrade-proof.md', 'text/markdown', 22, "
                    "'upgrade/proof.md', :checksum, 'ready') RETURNING id"
                ),
                {"owner_id": user_id, "checksum": "a" * 64},
            ).scalar_one()
            conversation_id = connection.execute(
                text(
                    "INSERT INTO conversations (owner_id, title) "
                    "VALUES (:owner_id, 'Upgrade proof') RETURNING id"
                ),
                {"owner_id": user_id},
            ).scalar_one()
            message_id = connection.execute(
                text(
                    "INSERT INTO conversation_messages "
                    "(conversation_id, role, content) "
                    "VALUES (:conversation_id, 'user', 'Preserve this message') "
                    "RETURNING id"
                ),
                {"conversation_id": conversation_id},
            ).scalar_one()

        alembic("upgrade", TARGET_REVISION)

        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == TARGET_REVISION
            )
            assert (
                connection.execute(
                    text("SELECT original_filename FROM documents WHERE id = :id"),
                    {"id": document_id},
                ).scalar_one()
                == "upgrade-proof.md"
            )
            assert (
                connection.execute(
                    text("SELECT content FROM conversation_messages WHERE id = :id"),
                    {"id": message_id},
                ).scalar_one()
                == "Preserve this message"
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = 'retrieval_runs' "
                        "AND column_name = 'selection_metrics'"
                    )
                ).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM pg_indexes "
                        "WHERE indexname IN "
                        "('ix_documents_search_vector_gin', "
                        "'ix_document_chunks_search_vector_gin')"
                    )
                ).scalar_one()
                == 2
            )
    finally:
        alembic("upgrade", "head")
        engine.dispose()
