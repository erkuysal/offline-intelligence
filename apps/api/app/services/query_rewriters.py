from abc import ABC, abstractmethod
import json

import httpx

from app.config import get_settings


class QueryRewriteError(Exception):
    pass


class QueryRewriter(ABC):
    model: str

    @abstractmethod
    def rewrite(self, query: str, *, max_variants: int) -> list[str]:
        raise NotImplementedError


class UnavailableQueryRewriter(QueryRewriter):
    def __init__(self, model: str) -> None:
        self.model = model

    def rewrite(self, query: str, *, max_variants: int) -> list[str]:
        raise QueryRewriteError("Query rewriting is disabled")


class FakeQueryRewriter(QueryRewriter):
    def __init__(self, model: str = "fake-query-rewriter") -> None:
        self.model = model

    def rewrite(self, query: str, *, max_variants: int) -> list[str]:
        return [f"{query} details", f"explain {query}"][:max_variants]


class OpenAICompatibleQueryRewriter(QueryRewriter):
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_tokens: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens

    def rewrite(self, query: str, *, max_variants: int) -> list[str]:
        if max_variants <= 0:
            return []
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Generate alternative search queries in the same language as the "
                                "user. Preserve names, identifiers, and intent. Return only a JSON "
                                "array of strings."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Return at most {max_variants} alternatives for: {query}",
                        },
                    ],
                    "temperature": 0,
                    "max_tokens": self.max_tokens,
                    "response_format": {
                        "type": "json_schema",
                        "schema": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": max_variants,
                        },
                    },
                },
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise QueryRewriteError("Query rewrite backend is unavailable") from exc
        if response.status_code >= 400:
            raise QueryRewriteError("Query rewrite backend rejected the request")
        try:
            content = response.json()["choices"][0]["message"]["content"]
            payload = json.loads(unwrap_json_code_fence(content))
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise QueryRewriteError("Query rewrite backend returned invalid JSON") from exc
        if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
            raise QueryRewriteError("Query rewrite backend returned an invalid variant list")
        return payload[:max_variants]


def unwrap_json_code_fence(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```") or not stripped.endswith("```"):
        return stripped
    first_newline = stripped.find("\n")
    if first_newline == -1:
        return stripped
    return stripped[first_newline + 1 : -3].strip()


def get_query_rewriter() -> QueryRewriter:
    settings = get_settings()
    backend = settings.query_rewrite_backend.strip().lower()
    if backend == "disabled":
        return UnavailableQueryRewriter(settings.query_rewrite_model)
    if backend == "fake":
        return FakeQueryRewriter(settings.query_rewrite_model)
    if backend in {"openai_compatible", "openai-compatible"}:
        return OpenAICompatibleQueryRewriter(
            settings.query_rewrite_base_url,
            settings.query_rewrite_model,
            settings.query_rewrite_timeout_seconds,
            settings.query_rewrite_max_tokens,
        )
    raise QueryRewriteError(f"Unsupported query rewrite backend: {settings.query_rewrite_backend}")
