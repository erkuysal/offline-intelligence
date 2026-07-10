import httpx
import pytest

from app.services.embeddings import EmbeddingError, OpenAICompatibleEmbeddingProvider


def test_openai_compatible_embedding_provider_sorts_and_coerces_vectors(monkeypatch) -> None:
    captured_payloads: list[dict] = []

    def fake_post(url: str, json: dict, timeout: float) -> httpx.Response:
        captured_payloads.append(json)
        assert url == "http://localhost:8081/v1/embeddings"
        assert timeout == 5
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [3, "4.5"]},
                    {"index": 0, "embedding": ["1", 2]},
                ]
            },
        )

    monkeypatch.setattr("app.services.embeddings.httpx.post", fake_post)
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://localhost:8081/v1/",
        model="embeddinggemma-300m",
        timeout_seconds=5,
        dimensions=768,
    )

    embeddings = provider.embed_texts(["alpha", "beta"])

    assert captured_payloads == [{"model": "embeddinggemma-300m", "input": ["alpha", "beta"]}]
    assert embeddings == [[1.0, 2.0], [3.0, 4.5]]


def test_openai_compatible_embedding_provider_rejects_invalid_vector_values(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.embeddings.httpx.post",
        lambda url, json, timeout: httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": ["not-a-number"]}]},
        ),
    )
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://localhost:8081/v1",
        model="embeddinggemma-300m",
        timeout_seconds=5,
        dimensions=768,
    )

    with pytest.raises(EmbeddingError, match="invalid response"):
        provider.embed_texts(["alpha"])


def test_openai_compatible_embedding_provider_maps_http_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.embeddings.httpx.post",
        lambda url, json, timeout: httpx.Response(500),
    )
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://localhost:8081/v1",
        model="embeddinggemma-300m",
        timeout_seconds=5,
        dimensions=768,
    )

    with pytest.raises(EmbeddingError, match="rejected"):
        provider.embed_texts(["alpha"])
