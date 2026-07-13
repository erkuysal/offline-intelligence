import os
import re

import psycopg
from sqlalchemy.engine import make_url


TEST_DATABASE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*_test$")


def main() -> None:
    database_url = make_url(os.environ["DATABASE_URL"])
    database_name = database_url.database or ""
    if not TEST_DATABASE_PATTERN.fullmatch(database_name):
        raise RuntimeError(
            f"Refusing to prepare non-test database: {database_name!r}",
        )

    admin_url = os.environ["TEST_DATABASE_ADMIN_URL"]
    with psycopg.connect(admin_url, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (database_name,),
        ).fetchone()
        if exists is None:
            connection.execute(f'CREATE DATABASE "{database_name}"')
            print(f"Created test database: {database_name}")
        else:
            print(f"Test database already exists: {database_name}")


if __name__ == "__main__":
    main()
