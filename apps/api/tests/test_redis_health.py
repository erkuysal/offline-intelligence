from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.main import app

client = TestClient(app)


def test_redis_health_check(monkeypatch) -> None:
    monkeypatch.setattr("app.main.ping_redis", lambda: True)

    response = client.get("/health/redis")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "redis": "reachable",
    }


def test_redis_health_check_returns_503_when_unavailable(monkeypatch) -> None:
    def raise_redis_error() -> None:
        raise RedisError("connection failed")

    monkeypatch.setattr("app.main.ping_redis", raise_redis_error)

    response = client.get("/health/redis")

    assert response.status_code == 503
    assert response.json() == {"detail": "Redis is unavailable"}
