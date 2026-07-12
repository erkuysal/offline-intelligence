from __future__ import annotations

import argparse
import os
import re
import shutil
from pathlib import Path

import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


E2E_DATABASE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*_e2e$")
DEFAULT_STORAGE_ROOT = Path("/tmp/offline-intelligence-hub-e2e")


def validate_environment() -> tuple[str, str, Path]:
    database_url = make_url(os.environ["DATABASE_URL"])
    database_name = database_url.database or ""
    if not E2E_DATABASE_PATTERN.fullmatch(database_name):
        raise RuntimeError(f"Refusing to manage non-E2E database: {database_name!r}")

    storage_dir = Path(os.environ["DOCUMENT_STORAGE_DIR"]).expanduser().resolve()
    storage_root = Path(
        os.environ.get("E2E_DOCUMENT_STORAGE_ROOT", DEFAULT_STORAGE_ROOT),
    ).expanduser().resolve()
    if storage_dir == storage_root or storage_root not in storage_dir.parents:
        raise RuntimeError(f"Refusing to manage storage outside {storage_root}: {storage_dir}")

    return database_url.render_as_string(hide_password=False), database_name, storage_dir


def setup() -> None:
    _, database_name, storage_dir = validate_environment()
    admin_url = os.environ["E2E_DATABASE_ADMIN_URL"]
    with psycopg.connect(admin_url, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (database_name,),
        ).fetchone()
        if exists is None:
            connection.execute(f'CREATE DATABASE "{database_name}"')
            print(f"Created E2E database: {database_name}")
        else:
            print(f"E2E database already exists: {database_name}")
    storage_dir.mkdir(parents=True, exist_ok=True)
    print(f"Prepared E2E document storage: {storage_dir}")


def cleanup() -> None:
    database_url, database_name, storage_dir = validate_environment()
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            tables = connection.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'",
                ),
            ).scalars().all()
            if tables:
                quoted_tables = ", ".join(f'"{table}"' for table in tables)
                connection.execute(text(f"TRUNCATE TABLE {quoted_tables} RESTART IDENTITY CASCADE"))
    finally:
        engine.dispose()

    if storage_dir.exists():
        shutil.rmtree(storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    print(f"Cleared E2E database and document storage: {database_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the isolated browser-test environment")
    parser.add_argument("action", choices=("setup", "cleanup"))
    args = parser.parse_args()
    if args.action == "setup":
        setup()
    else:
        cleanup()


if __name__ == "__main__":
    main()
