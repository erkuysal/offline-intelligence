from abc import ABC, abstractmethod
import hashlib
import json
import math
import re

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.document import Document, DocumentChunk

TOKEN_RE = re.compile(r"[a-z0-9]+")


class EmbeddingError(Exception):
    pass


class UnsupportedEmbeddingBackendError(EmbeddingError):
    pass


class EmbeddingProvider(ABC):
    model: str

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model: str, dimensions: int) -> None:
        self.model = model
        self.dimensions = dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_text(text) for text in texts]

    def _embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0
        return normalize_vector(vector)


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(self, base_url: str, model: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": self.model,
            "input": texts,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/embeddings",
                json=payload,
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise EmbeddingError("Embedding backend is unavailable") from exc

        if response.status_code >= 400:
            raise EmbeddingError("Embedding backend rejected the request")

        try:
            data = response.json()
            return [item["embedding"] for item in sorted(data["data"], key=lambda item: item["index"])]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError("Embedding backend returned an invalid response") from exc


def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    backend = settings.embedding_backend.strip().lower()

    if backend == "fake":
        return FakeEmbeddingProvider(
            model=settings.embedding_model,
            dimensions=settings.fake_embedding_dimensions,
        )

    if backend in {"openai_compatible", "openai-compatible"}:
        return OpenAICompatibleEmbeddingProvider(
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            timeout_seconds=settings.embedding_timeout_seconds,
        )

    raise UnsupportedEmbeddingBackendError(f"Unsupported embedding backend: {settings.embedding_backend}")


def embed_document_chunks(
    db: Session,
    document: Document,
    provider: EmbeddingProvider,
) -> None:
    chunks = list(document.chunks)
    if not chunks:
        return

    embeddings = provider.embed_texts([chunk.content for chunk in chunks])
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        chunk.embedding_json = json.dumps(embedding, separators=(",", ":"))
        chunk.embedding_model = provider.model
    db.commit()


def search_document_chunks(
    db: Session,
    *,
    owner_id: int,
    query: str,
    limit: int,
    provider: EmbeddingProvider,
    document_ids: list[int] | None = None,
) -> list[tuple[DocumentChunk, float]]:
    query_embedding = provider.embed_texts([query])[0]
    statement = (
        select(DocumentChunk)
        .join(Document)
        .where(
            Document.owner_id == owner_id,
            Document.status == "ready",
            DocumentChunk.embedding_json.is_not(None),
        )
    )
    if document_ids is not None:
        statement = statement.where(Document.id.in_(document_ids))

    scored_chunks: list[tuple[DocumentChunk, float]] = []
    for chunk in db.scalars(statement):
        embedding = parse_embedding(chunk.embedding_json)
        if embedding is None:
            continue
        scored_chunks.append((chunk, cosine_similarity(query_embedding, embedding)))

    scored_chunks.sort(key=lambda item: item[1], reverse=True)
    return scored_chunks[:limit]


def parse_embedding(raw_embedding: str | None) -> list[float] | None:
    if raw_embedding is None:
        return None
    try:
        value = json.loads(raw_embedding)
    except ValueError:
        return None
    if not isinstance(value, list):
        return None
    return [float(item) for item in value]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    left_norm = vector_norm(left)
    right_norm = vector_norm(right)
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )


def normalize_vector(vector: list[float]) -> list[float]:
    norm = vector_norm(vector)
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def vector_norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))
