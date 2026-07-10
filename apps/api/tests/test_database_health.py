import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
pytestmark = pytest.mark.usefixtures("clean_database")


def test_database_health_check() -> None:
    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "database": "reachable",
    }
