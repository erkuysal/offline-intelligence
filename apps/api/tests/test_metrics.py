from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

client = TestClient(app)


def test_metrics_returns_prometheus_exposition() -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "offline_hub_http_requests_total" in response.text
    assert "offline_hub_llm_requests_total" in response.text
    assert "offline_hub_llm_request_duration_seconds" in response.text
    assert "offline_hub_llm_tokens_total" in response.text
    assert "offline_hub_llm_active_requests" in response.text
    assert "offline_hub_llm_warmup_attempts_total" in response.text


def test_metrics_json_returns_diagnostic_snapshot() -> None:
    settings = get_settings()
    response = client.get("/metrics.json")

    assert response.status_code == 200
    body = response.json()
    assert body["app"]["name"] == settings.app_name
    assert body["app"]["version"] == settings.app_version
    assert body["app"]["environment"] == settings.environment
    assert body["uptime_seconds"] >= 0
    assert body["requests_total"] >= 0
    assert isinstance(body["requests"], list)
    assert body["llm_requests_total"] >= 0
    assert isinstance(body["llm_requests"], list)
    assert isinstance(body["llm_warmups"], list)
    assert body["llm_readiness"]["status"] in {
        "disabled",
        "warming",
        "ready",
        "unavailable",
    }
    for request in body["llm_requests"]:
        assert request["prompt_tokens"] >= 0
        assert request["completion_tokens"] >= 0
        assert request["total_tokens"] >= 0


def test_metrics_request_counter_increments() -> None:
    before_response = client.get("/metrics.json")
    before_total = before_response.json()["requests_total"]

    health_response = client.get("/health")
    after_response = client.get("/metrics.json")

    assert health_response.status_code == 200
    after_body = after_response.json()
    assert after_body["requests_total"] >= before_total + 2
    assert any(
        request["method"] == "GET"
        and request["path"] == "/health"
        and request["status_code"] == 200
        and request["count"] >= 1
        for request in after_body["requests"]
    )

    prometheus_response = client.get("/metrics")
    assert 'path="/health"' in prometheus_response.text
    assert 'status_code="200"' in prometheus_response.text
