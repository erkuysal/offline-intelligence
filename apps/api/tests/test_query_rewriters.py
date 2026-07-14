import httpx
import pytest

from app.services.query_rewriters import OpenAICompatibleQueryRewriter, QueryRewriteError


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self.payload


def test_openai_compatible_rewriter_requests_bounded_json_variants(monkeypatch) -> None:
    captured = {}

    def post(url, *, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return FakeResponse(
            {"choices": [{"message": {"content": '["nightly backup", "restore policy"]'}}]}
        )

    monkeypatch.setattr(httpx, "post", post)
    rewriter = OpenAICompatibleQueryRewriter("http://localhost:8080/v1", "local", 3.0, 96)

    assert rewriter.rewrite("backup schedule", max_variants=2) == [
        "nightly backup",
        "restore policy",
    ]
    assert captured["url"] == "http://localhost:8080/v1/chat/completions"
    assert captured["timeout"] == 3.0
    assert captured["json"]["temperature"] == 0
    assert captured["json"]["max_tokens"] == 96
    assert captured["json"]["response_format"]["schema"]["maxItems"] == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": [{"message": {"content": "not json"}}]},
        {"choices": [{"message": {"content": '{"query": "wrong shape"}'}}]},
        {"choices": [{"message": {"content": '["valid", 3]'}}]},
        {"unexpected": []},
    ],
)
def test_openai_compatible_rewriter_rejects_invalid_results(monkeypatch, payload) -> None:
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeResponse(payload))
    rewriter = OpenAICompatibleQueryRewriter("http://localhost:8080/v1", "local", 3.0, 96)

    with pytest.raises(QueryRewriteError):
        rewriter.rewrite("backup schedule", max_variants=2)


def test_openai_compatible_rewriter_maps_transport_failure(monkeypatch) -> None:
    def post(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "post", post)
    rewriter = OpenAICompatibleQueryRewriter("http://localhost:8080/v1", "local", 3.0, 96)

    with pytest.raises(QueryRewriteError, match="unavailable"):
        rewriter.rewrite("backup schedule", max_variants=2)


def test_openai_compatible_rewriter_accepts_one_complete_json_fence(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '```json\n["first", "second", "bounded out"]\n```'
                        }
                    }
                ]
            }
        ),
    )
    rewriter = OpenAICompatibleQueryRewriter("http://localhost:8080/v1", "local", 3.0, 96)

    assert rewriter.rewrite("query", max_variants=2) == ["first", "second"]
