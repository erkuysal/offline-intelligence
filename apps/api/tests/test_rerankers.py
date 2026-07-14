import httpx
import pytest

from app.services.rerankers import LlamaCppRerankerProvider, RerankerError


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self.payload


def test_llama_cpp_reranker_restores_input_index_order(monkeypatch) -> None:
    captured = {}

    def post(url, *, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return FakeResponse(
            {
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                ]
            }
        )

    monkeypatch.setattr(httpx, "post", post)
    provider = LlamaCppRerankerProvider("http://localhost:8082/v1", "reranker", 4.0)

    assert provider.score("query", ["first", "second"]) == [0.2, 0.9]
    assert captured == {
        "url": "http://localhost:8082/v1/rerank",
        "json": {
            "model": "reranker",
            "query": "query",
            "documents": ["first", "second"],
            "top_n": 2,
            "normalize": True,
        },
        "timeout": 4.0,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"results": [{"index": 0, "relevance_score": 0.5}]},
        {"results": [{"index": 0, "relevance_score": float("nan")}]},
        {"unexpected": []},
    ],
)
def test_llama_cpp_reranker_rejects_invalid_results(monkeypatch, payload) -> None:
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeResponse(payload))
    provider = LlamaCppRerankerProvider("http://localhost:8082/v1", "reranker", 4.0)

    with pytest.raises(RerankerError):
        provider.score("query", ["first", "second"])
