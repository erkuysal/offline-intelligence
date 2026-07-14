from abc import ABC, abstractmethod
import math

import httpx

from app.config import get_settings


class RerankerError(Exception):
    pass


class RerankerProvider(ABC):
    model: str

    @abstractmethod
    def score(self, query: str, documents: list[str]) -> list[float]:
        raise NotImplementedError


class UnavailableRerankerProvider(RerankerProvider):
    def __init__(self, model: str) -> None:
        self.model = model

    def score(self, query: str, documents: list[str]) -> list[float]:
        raise RerankerError("Reranker backend is disabled")


class FakeRerankerProvider(RerankerProvider):
    def __init__(self, model: str = "fake-token-overlap") -> None:
        self.model = model

    def score(self, query: str, documents: list[str]) -> list[float]:
        query_tokens = set(query.lower().split())
        return [
            len(query_tokens & set(document.lower().split())) / max(1, len(query_tokens))
            for document in documents
        ]


class LlamaCppRerankerProvider(RerankerProvider):
    def __init__(self, base_url: str, model: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        try:
            response = httpx.post(
                f"{self.base_url}/rerank",
                json={
                    "model": self.model,
                    "query": query,
                    "documents": documents,
                    "top_n": len(documents),
                    "normalize": True,
                },
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise RerankerError("Reranker backend is unavailable") from exc
        if response.status_code >= 400:
            raise RerankerError("Reranker backend rejected the request")
        try:
            results = response.json()["results"]
            scores_by_index = {
                int(item["index"]): float(item["relevance_score"])
                for item in results
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RerankerError("Reranker backend returned an invalid response") from exc
        expected_indexes = set(range(len(documents)))
        if set(scores_by_index) != expected_indexes or len(results) != len(documents):
            raise RerankerError("Reranker backend returned incomplete results")
        scores = [scores_by_index[index] for index in range(len(documents))]
        if not all(math.isfinite(score) for score in scores):
            raise RerankerError("Reranker backend returned a non-finite score")
        return scores


def get_reranker_provider() -> RerankerProvider:
    settings = get_settings()
    backend = settings.reranker_backend.strip().lower()
    if backend == "disabled":
        return UnavailableRerankerProvider(settings.reranker_model)
    if backend == "fake":
        return FakeRerankerProvider(settings.reranker_model)
    if backend in {"openai_compatible", "openai-compatible", "llama_cpp", "llama-cpp"}:
        return LlamaCppRerankerProvider(
            settings.reranker_base_url,
            settings.reranker_model,
            settings.reranker_timeout_seconds,
        )
    raise RerankerError(f"Unsupported reranker backend: {settings.reranker_backend}")
