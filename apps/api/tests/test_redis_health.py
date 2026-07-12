from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.main import app

client = TestClient(app)


def test_redis_health_check(monkeypatch) -> None:
    monkeypatch.setattr("app.main.ping_redis", lambda: True)

    response = client.get("/health/redis")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "redis"
    assert body["status"] == "healthy"
    assert body["detail"] == "Redis is reachable"


def test_redis_health_check_returns_503_when_unavailable(monkeypatch) -> None:
    def raise_redis_error() -> None:
        raise RedisError("redis://user:password@private-host")

    monkeypatch.setattr("app.main.ping_redis", raise_redis_error)

    response = client.get("/health/redis")

    assert response.status_code == 503
    body = response.json()
    assert body["service"] == "redis"
    assert body["status"] == "unavailable"
    assert body["detail"] == "Redis connection failed"
    assert body["code"] == "redis_unavailable"
    assert "private-host" not in response.text
