from abc import ABC, abstractmethod
import hashlib
import math
import re

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.constants import EMBEDDING_DIMENSIONS
from app.models.document import Document, DocumentChunk

TOKEN_RE = re.compile(r"[a-z0-9]+")


class EmbeddingError(Exception):
    pass


class UnsupportedEmbeddingBackendError(EmbeddingError):
    pass


class EmbeddingProvider(ABC):
    model: str
    dimensions: int

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
    def __init__(self, base_url: str, model: str, timeout_seconds: float, dimensions: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.dimensions = dimensions

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
            return [
                coerce_embedding(item["embedding"])
                for item in sorted(data["data"], key=lambda item: item["index"])
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError("Embedding backend returned an invalid response") from exc


def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    backend = settings.embedding_backend.strip().lower()

    if backend == "fake":
        return FakeEmbeddingProvider(
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )

    if backend in {"openai_compatible", "openai-compatible"}:
        return OpenAICompatibleEmbeddingProvider(
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            timeout_seconds=settings.embedding_timeout_seconds,
            dimensions=settings.embedding_dimensions,
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
    validate_embeddings(embeddings, expected_count=len(chunks), dimensions=EMBEDDING_DIMENSIONS)
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        chunk.embedding = embedding
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
    query_embeddings = provider.embed_texts([query])
    validate_embeddings(query_embeddings, expected_count=1, dimensions=EMBEDDING_DIMENSIONS)
    query_embedding = query_embeddings[0]
    distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    statement = (
        select(DocumentChunk, (1 - distance).label("score"))
        .join(Document)
        .where(
            Document.owner_id == owner_id,
            Document.status == "ready",
            DocumentChunk.embedding.is_not(None),
            DocumentChunk.embedding_model == provider.model,
        )
        .order_by(distance)
        .limit(limit)
    )
    if document_ids is not None:
        statement = statement.where(Document.id.in_(document_ids))

    return [(chunk, float(score)) for chunk, score in db.execute(statement)]


def reembed_all_document_chunks(
    db: Session,
    *,
    provider: EmbeddingProvider,
    batch_size: int,
    stale_only: bool = False,
) -> int:
    processed = 0
    last_chunk_id = 0

    while True:
        statement = (
            select(DocumentChunk)
            .join(Document)
            .where(
                Document.status == "ready",
                DocumentChunk.id > last_chunk_id,
            )
            .order_by(DocumentChunk.id)
            .limit(batch_size)
        )
        if stale_only:
            statement = statement.where(
                or_(
                    DocumentChunk.embedding.is_(None),
                    DocumentChunk.embedding_model.is_(None),
                    DocumentChunk.embedding_model != provider.model,
                )
            )
        chunks = list(db.scalars(statement))
        if not chunks:
            break

        embeddings = provider.embed_texts([chunk.content for chunk in chunks])
        validate_embeddings(embeddings, expected_count=len(chunks), dimensions=EMBEDDING_DIMENSIONS)
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            chunk.embedding = embedding
            chunk.embedding_model = provider.model
        db.commit()

        processed += len(chunks)
        last_chunk_id = chunks[-1].id

    return processed


def validate_embeddings(
    embeddings: list[list[float]],
    *,
    expected_count: int,
    dimensions: int,
) -> None:
    if len(embeddings) != expected_count:
        raise EmbeddingError("Embedding backend returned an unexpected number of vectors")
    for embedding in embeddings:
        if len(embedding) != dimensions:
            raise EmbeddingError(
                f"Embedding backend returned {len(embedding)} dimensions; expected {dimensions}"
            )
        if not all(isinstance(value, int | float) and math.isfinite(value) for value in embedding):
            raise EmbeddingError("Embedding backend returned a non-finite vector")


def coerce_embedding(embedding: object) -> list[float]:
    if not isinstance(embedding, list):
        raise ValueError("embedding must be a list")
    return [float(value) for value in embedding]


def normalize_vector(vector: list[float]) -> list[float]:
    norm = vector_norm(vector)
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def vector_norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))
