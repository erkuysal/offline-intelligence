from pathlib import Path
from time import perf_counter
from uuid import uuid4
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.v1.chat import llm_request_semaphore, parse_stream_event, stream_llm_response
from app.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models.retrieval import RetrievalRun
from app.schemas.chat import ChatCompletionRequest
from app.services.llm import LLMTimeoutError, LLMUnavailableError

client = TestClient(app)
pytestmark = pytest.mark.usefixtures("clean_database")


def get_access_token() -> str:
    email = f"chat-user-{uuid4().hex}@example.com"
    password = "correct-horse-battery-staple"
    client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
        },
    )
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )
    return response.json()["access_token"]


def upload_document(token: str, content: str, filename: str) -> dict:
    response = client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, content.encode(), "text/plain")},
    )
    assert response.status_code == 201
    return response.json()


def test_chat_completion_requires_authentication() -> None:
    response = client.post(
        "/api/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 401


def test_chat_completion_uses_fake_backend() -> None:
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Explain Phase 2"}],
            "temperature": 0.2,
            "max_tokens": 64,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == get_settings().llm_model
    assert body["choices"][0]["message"] == {
        "role": "assistant",
        "content": "Fake LLM response: Explain Phase 2",
    }
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"] == {
        "prompt_tokens": 3,
        "completion_tokens": 6,
        "total_tokens": 9,
    }
    assert body["conversation_id"] is not None


def test_chat_completion_persists_conversation_messages() -> None:
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Remember this"}],
            "max_tokens": 64,
        },
    )
    conversation_id = response.json()["conversation_id"]
    conversations_response = client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    messages_response = client.get(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert conversations_response.status_code == 200
    assert conversations_response.json()[0]["id"] == conversation_id
    assert messages_response.status_code == 200
    assert [(message["role"], message["content"]) for message in messages_response.json()] == [
        ("user", "Remember this"),
        ("assistant", "Fake LLM response: Remember this"),
    ]


def test_chat_completion_records_success_metric() -> None:
    token = get_access_token()
    before_response = client.get("/metrics.json")
    before_total = before_response.json()["llm_requests_total"]

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 64,
        },
    )
    after_response = client.get("/metrics.json")

    assert response.status_code == 200
    after_body = after_response.json()
    assert after_body["llm_requests_total"] >= before_total + 1
    assert any(
        request["backend"] == get_settings().llm_backend
        and request["model"] == get_settings().llm_model
        and request["outcome"] == "success"
        and request["count"] >= 1
        and request["total_latency_ms"] >= 0
        and request["prompt_tokens"] >= 1
        and request["completion_tokens"] >= 1
        and request["total_tokens"] >= 2
        for request in after_body["llm_requests"]
    )


def test_chat_completion_streams_fake_backend() -> None:
    token = get_access_token()
    before_response = client.get("/metrics.json")
    before_total = before_response.json()["llm_requests_total"]

    with client.stream(
        "POST",
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={"messages": [{"role": "user", "content": "Hello"}], "stream": True},
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: " in body
    assert "Fake LLM response: Hello" in body
    assert "event: complete" in body
    assert "data: [DONE]" in body
    complete_payload = next(
        json.loads(line.removeprefix("data: "))
        for index, line in enumerate(body.splitlines())
        if index > 0 and body.splitlines()[index - 1] == "event: complete" and line.startswith("data: ")
    )
    conversation_id = complete_payload["conversation_id"]
    messages = client.get(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert [(message["role"], message["content"]) for message in messages] == [
        ("user", "Hello"),
        ("assistant", "Fake LLM response: Hello"),
    ]
    assert messages[-1]["model"] == get_settings().llm_model
    assert messages[-1]["prompt_tokens"] == complete_payload["usage"]["prompt_tokens"]
    assert messages[-1]["completion_tokens"] == complete_payload["usage"]["completion_tokens"]
    assert messages[-1]["total_tokens"] == complete_payload["usage"]["total_tokens"]
    after_body = client.get("/metrics.json").json()
    assert after_body["llm_requests_total"] >= before_total + 1
    assert any(
        request["backend"] == get_settings().llm_backend
        and request["model"] == get_settings().llm_model
        and request["outcome"] == "stream_success"
        and request["count"] >= 1
        and request["prompt_tokens"] >= 1
        and request["completion_tokens"] >= 1
        and request["total_tokens"] >= 2
        for request in after_body["llm_requests"]
    )


def test_parse_stream_event_returns_content_and_usage() -> None:
    usage, content = parse_stream_event(
        'data: {"choices":[{"delta":{"content":"Hello"}}],'
        '"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}\n\n'
    )

    assert content == "Hello"
    assert usage is not None
    assert usage.prompt_tokens == 2
    assert usage.completion_tokens == 1
    assert usage.total_tokens == 3


def test_stream_estimates_usage_when_backend_omits_it() -> None:
    class BackendWithoutUsage:
        def stream_chat(self, request: ChatCompletionRequest):
            yield 'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            yield "data: [DONE]\n\n"

    request = ChatCompletionRequest(
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
    )
    assert llm_request_semaphore.acquire(blocking=False) is True

    events = list(stream_llm_response(BackendWithoutUsage(), request, perf_counter()))

    assert events[-1] == "data: [DONE]\n\n"
    assert any(
        metric["outcome"] == "stream_success"
        and metric["prompt_tokens"] >= 1
        and metric["completion_tokens"] >= 1
        for metric in client.get("/metrics.json").json()["llm_requests"]
    )


def test_chat_completion_retrieves_document_sources(tmp_path: Path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    token = get_access_token()
    document = upload_document(
        token,
        "Backups run every night. Restore checks happen weekly.",
        "backup-policy.txt",
    )
    chunks = client.get(
        f"/api/v1/documents/{document['id']}/chunks",
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "When do backups run?"}],
            "use_documents": True,
            "document_ids": [document["id"]],
            "retrieval_limit": 1,
            "retrieval_strategy": "hybrid",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "Fake LLM response: When do backups run?"
    assert body["sources"] == [
        {
            "document_id": document["id"],
            "document_filename": "backup-policy.txt",
            "chunk_id": chunks[0]["id"],
            "chunk_index": 0,
            "source_page": None,
            "source_label": "backup-policy.txt",
            "content": chunks[0]["content"],
            "char_start": chunks[0]["char_start"],
            "char_end": chunks[0]["char_end"],
            "score": body["sources"][0]["score"],
        }
    ]
    messages_response = client.get(
        f"/api/v1/chat/conversations/{body['conversation_id']}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assistant_message = messages_response.json()[-1]

    assert assistant_message["role"] == "assistant"
    assert assistant_message["sources"][0]["chunk_id"] == chunks[0]["id"]
    assert assistant_message["sources"][0]["content"] == chunks[0]["content"]
    assert assistant_message["sources"][0]["char_start"] == chunks[0]["char_start"]
    assert assistant_message["sources"][0]["char_end"] == chunks[0]["char_end"]
    assert assistant_message["sources"][0]["document_accessible"] is True
    with SessionLocal() as db:
        run = db.scalar(select(RetrievalRun).order_by(RetrievalRun.id.desc()))
    assert run is not None
    assert run.request_kind == "chat"
    assert run.strategy == "hybrid"
    assert run.query_text is None
    assert run.filters == {"document_ids": [document["id"]], "limit": 1}
    assert run.candidate_count == 1
    assert run.selected_context_count == 1
    assert run.model_versions == {
        "embedding": "fake-bow",
        "lexical": "postgresql-simple",
    }
    assert run.candidates[0]["strategy"] == "hybrid"
    assert set(run.candidates[0]["strategy_ranks"]) == {"dense", "lexical"}
    assert set(run.timings_ms) >= {
        "dense_embedding",
        "dense_candidate_retrieval",
        "lexical_candidate_retrieval",
        "fusion",
        "strategy_total",
        "context_selection",
        "pipeline_total",
    }
    assert run.selection_metrics == {
        "input_candidate_count": 1,
        "selected_candidate_count": 1,
        "exact_duplicates_removed": 0,
        "overlap_chars_removed": 0,
        "considered_chars": len(chunks[0]["content"]),
        "unique_chars": len(chunks[0]["content"]),
        "selected_chars": len(chunks[0]["content"]),
        "unique_context_ratio": 1.0,
    }


def test_streaming_chat_emits_document_sources(tmp_path: Path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    token = get_access_token()
    upload_document(token, "The support desk opens at nine.", "support.txt")

    with client.stream(
        "POST",
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "When does support open?"}],
            "use_documents": True,
            "stream": True,
        },
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert "event: sources" in body
    assert '"document_filename":"support.txt"' in body
    assert "Fake LLM response: When does support open?" in body
    complete_data = json.loads(
        body.split("event: complete\ndata: ", maxsplit=1)[1].split("\n", maxsplit=1)[0]
    )
    messages = client.get(
        f"/api/v1/chat/conversations/{complete_data['conversation_id']}/messages",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert messages[-1]["sources"][0]["document_filename"] == "support.txt"


def test_rag_chat_hides_other_users_documents(tmp_path: Path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    owner_token = get_access_token()
    other_token = get_access_token()
    document = upload_document(owner_token, "Private launch code alpha.", "private.txt")

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {other_token}"},
        json={
            "messages": [{"role": "user", "content": "What is the launch code?"}],
            "use_documents": True,
            "document_ids": [document["id"]],
        },
    )

    assert response.status_code == 200
    assert response.json()["sources"] is None


def test_conversation_detail_and_delete_are_owner_only() -> None:
    owner_token = get_access_token()
    other_token = get_access_token()
    completion = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"messages": [{"role": "user", "content": "Private conversation"}]},
    )
    conversation_id = completion.json()["conversation_id"]

    detail = client.get(
        f"/api/v1/chat/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == conversation_id

    for method, path in (
        ("get", f"/api/v1/chat/conversations/{conversation_id}"),
        ("get", f"/api/v1/chat/conversations/{conversation_id}/messages"),
        ("delete", f"/api/v1/chat/conversations/{conversation_id}"),
    ):
        response = getattr(client, method)(
            path,
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "Conversation not found"}

    deletion = client.delete(
        f"/api/v1/chat/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert deletion.status_code == 204
    assert client.get(
        f"/api/v1/chat/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).status_code == 404
    assert client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json() == []


def test_conversation_redacts_passage_after_cited_document_is_deleted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    token = get_access_token()
    document = upload_document(token, "A confidential retained passage.", "retained.txt")
    completion = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "What is retained?"}],
            "use_documents": True,
            "document_ids": [document["id"]],
        },
    ).json()
    messages_url = f"/api/v1/chat/conversations/{completion['conversation_id']}/messages"

    source_before = client.get(
        messages_url,
        headers={"Authorization": f"Bearer {token}"},
    ).json()[-1]["sources"][0]
    assert source_before["document_accessible"] is True
    assert source_before["content"] == "A confidential retained passage."

    deletion = client.delete(
        f"/api/v1/documents/{document['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deletion.status_code == 204
    source_after = client.get(
        messages_url,
        headers={"Authorization": f"Bearer {token}"},
    ).json()[-1]["sources"][0]
    assert source_after["document_accessible"] is False
    assert source_after["content"] is None
    assert source_after["chunk_id"] is None


def test_stream_cancellation_records_metric_and_releases_semaphore() -> None:
    class StreamingBackend:
        def stream_chat(self, request: ChatCompletionRequest):
            yield "data: first\n\n"
            yield "data: second\n\n"

    request = ChatCompletionRequest(
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
    )
    before_total = client.get("/metrics.json").json()["llm_requests_total"]
    acquired = llm_request_semaphore.acquire(blocking=False)
    assert acquired is True

    stream = stream_llm_response(StreamingBackend(), request, 0)
    assert next(stream) == "data: first\n\n"
    stream.close()

    reacquired = llm_request_semaphore.acquire(blocking=False)
    assert reacquired is True
    llm_request_semaphore.release()
    after_body = client.get("/metrics.json").json()
    assert after_body["llm_requests_total"] >= before_total + 1
    assert any(
        request["outcome"] == "stream_cancelled" and request["count"] >= 1
        for request in after_body["llm_requests"]
    )
    assert "offline_hub_llm_active_requests 0.0" in client.get("/metrics").text


@pytest.mark.parametrize(
    ("exception", "code", "detail"),
    [
        (LLMTimeoutError("timeout"), "llm_timeout", "LLM backend timed out"),
        (LLMUnavailableError("offline"), "llm_unavailable", "LLM backend is unavailable"),
    ],
)
def test_stream_failures_emit_stable_error_and_release_semaphore(
    exception: Exception,
    code: str,
    detail: str,
) -> None:
    class FailingBackend:
        def stream_chat(self, request: ChatCompletionRequest):
            raise exception
            yield

    request = ChatCompletionRequest(
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
    )
    assert llm_request_semaphore.acquire(blocking=False) is True

    body = "".join(stream_llm_response(FailingBackend(), request, perf_counter()))

    assert f'"code":"{code}"' in body
    assert f'"detail":"{detail}"' in body
    assert '"retryable":true' in body
    assert "event: complete" not in body
    assert "data: [DONE]" not in body
    assert llm_request_semaphore.acquire(blocking=False) is True
    llm_request_semaphore.release()


def test_stream_rejects_unknown_conversation_before_sending_headers() -> None:
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "conversation_id": 999999,
            "stream": True,
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


def test_chat_completion_validates_message_role() -> None:
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "tool", "content": "Hello"}],
        },
    )

    assert response.status_code == 422


def test_chat_completion_rejects_total_message_chars_over_limit(monkeypatch) -> None:
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "llm_max_total_message_chars", 4)
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": "Chat messages exceed configured LLM input size limit",
    }


def test_chat_completion_rejects_max_tokens_over_limit(monkeypatch) -> None:
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "llm_max_completion_tokens", 10)
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 11,
        },
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": "Requested completion tokens exceed configured LLM output limit",
    }


def test_chat_completion_returns_429_when_llm_is_busy(monkeypatch) -> None:
    was_called = False

    class Backend:
        def complete_chat(self, request: ChatCompletionRequest) -> None:
            nonlocal was_called
            was_called = True

    import app.api.v1.chat as chat_module

    acquired = chat_module.llm_request_semaphore.acquire(blocking=False)
    assert acquired is True
    monkeypatch.setattr("app.api.v1.chat.get_llm_backend", lambda: Backend())
    token = get_access_token()

    try:
        response = client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
    finally:
        chat_module.llm_request_semaphore.release()

    assert response.status_code == 429
    assert response.json() == {"detail": "LLM backend is busy"}
    assert was_called is False
    assert 'reason="busy"' in client.get("/metrics").text


def test_chat_completion_returns_503_when_backend_is_unavailable(monkeypatch) -> None:
    class UnavailableBackend:
        def complete_chat(self, request: ChatCompletionRequest) -> None:
            raise LLMUnavailableError("offline")

    monkeypatch.setattr(
        "app.api.v1.chat.get_llm_backend",
        lambda: UnavailableBackend(),
    )
    token = get_access_token()
    before_response = client.get("/metrics.json")
    before_total = before_response.json()["llm_requests_total"]

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "LLM backend is unavailable"}
    after_body = client.get("/metrics.json").json()
    assert after_body["llm_requests_total"] >= before_total + 1
    assert any(
        request["outcome"] == "unavailable" and request["count"] >= 1
        for request in after_body["llm_requests"]
    )


def test_chat_completion_returns_504_when_backend_times_out(monkeypatch) -> None:
    class TimeoutBackend:
        def complete_chat(self, request: ChatCompletionRequest) -> None:
            raise LLMTimeoutError("timeout")

    monkeypatch.setattr(
        "app.api.v1.chat.get_llm_backend",
        lambda: TimeoutBackend(),
    )
    token = get_access_token()

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 504
    assert response.json() == {"detail": "LLM backend timed out"}
