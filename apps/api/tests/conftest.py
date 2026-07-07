import pytest
from sqlalchemy import text

from app.db.session import engine


@pytest.fixture(autouse=True)
def clean_database() -> None:
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE TABLE user_roles, documents, users, roles RESTART IDENTITY CASCADE")
        )

    yield

    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE TABLE user_roles, documents, users, roles RESTART IDENTITY CASCADE")
        )
