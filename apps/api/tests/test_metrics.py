from fastapi.testclient import TestClient
from pathlib import Path
from uuid import uuid4

import pytest

from app.config import get_settings
from app.main import app

client = TestClient(app)
pytestmark = pytest.mark.usefixtures("clean_database")


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
    assert "offline_hub_operations_total" in response.text
    assert "offline_hub_operation_duration_seconds" in response.text
    assert "offline_hub_operation_items_total" in response.text


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
    assert isinstance(body["operations"], list)
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


def test_metrics_cover_ingestion_embedding_and_retrieval_outcomes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    successful_upload = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("metrics.txt", b"Operational metrics passage.", "text/plain")},
    )
    assert successful_upload.status_code == 201
    document_id = successful_upload.json()["id"]
    retrieval = client.post(
        "/api/v1/chat/completions",
        headers=headers,
        json={
            "messages": [{"role": "user", "content": "What passage is operational?"}],
            "use_documents": True,
            "document_ids": [document_id],
        },
    )
    assert retrieval.status_code == 200
    multi_query_retrieval = client.post(
        "/api/v1/chat/completions",
        headers=headers,
        json={
            "messages": [{"role": "user", "content": "What passage is operational?"}],
            "use_documents": True,
            "document_ids": [document_id],
            "retrieval_strategy": "multi_query",
        },
    )
    assert multi_query_retrieval.status_code == 200
    failed_upload = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("broken.txt", bytes([0xFF, 0xFE]), "text/plain")},
    )
    assert failed_upload.status_code == 201
    assert failed_upload.json()["status"] == "failed"

    operations = client.get("/metrics.json").json()["operations"]
    assert_operation(operations, stage="ingestion", operation="process_document", outcome="success")
    assert_operation(operations, stage="ingestion", operation="process_document", outcome="failure")
    assert_operation(operations, stage="embedding", operation="document", outcome="success")
    assert_operation(operations, stage="embedding", operation="query", outcome="success")
    retrieval_metric = assert_operation(
        operations,
        stage="retrieval",
        operation="dense_search",
        outcome="success",
    )
    assert retrieval_metric["item_count"] >= 1
    context_metric = assert_operation(
        operations,
        stage="retrieval",
        operation="context_selection",
        outcome="success",
    )
    assert context_metric["item_count"] >= 1
    assert_operation(
        operations,
        stage="retrieval",
        operation="query_rewrite",
        outcome="fallback",
    )
    assert_operation(
        operations,
        stage="retrieval",
        operation="multi_query_merge",
        outcome="success",
    )
    assert_operation(
        operations,
        stage="retrieval",
        operation="context_exact_deduplication",
        outcome="unchanged",
    )
    assert_operation(
        operations,
        stage="retrieval",
        operation="context_overlap_deduplication",
        outcome="unchanged",
    )
    persistence_metric = assert_operation(
        operations,
        stage="retrieval",
        operation="persist_run",
        outcome="success",
    )
    assert persistence_metric["item_count"] >= 1


def get_access_token() -> str:
    email = f"metrics-{uuid4().hex}@example.com"
    password = "correct-horse-battery-staple"
    assert client.post("/api/v1/auth/register", json={"email": email, "password": password}).status_code == 201
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def assert_operation(
    operations: list[dict],
    *,
    stage: str,
    operation: str,
    outcome: str,
) -> dict:
    metric = next(
        item
        for item in operations
        if item["stage"] == stage and item["operation"] == operation and item["outcome"] == outcome
    )
    assert metric["count"] >= 1
    assert metric["total_latency_ms"] >= 0
    assert metric["item_count"] >= 0
    return metric
