import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db.session import engine


def pytest_sessionstart() -> None:
    settings = get_settings()
    database_name = make_url(settings.database_url).database or ""
    if settings.environment != "testing" or not database_name.endswith("_test"):
        raise RuntimeError(
            "Refusing to run tests unless ENVIRONMENT=testing and DATABASE_URL targets a *_test database",
        )


@pytest.fixture(autouse=True)
def clean_database() -> None:
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE TABLE user_roles, document_chunks, documents, users, roles RESTART IDENTITY CASCADE")
        )

    yield

    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE TABLE user_roles, document_chunks, documents, users, roles RESTART IDENTITY CASCADE")
        )
