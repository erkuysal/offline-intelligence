from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    original_filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    status: str
    chunk_count: int
    ingestion_error: str | None
    version_number: int
    created_at: datetime
    updated_at: datetime


class DocumentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_number: int
    original_filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    created_at: datetime


class DocumentPermissionCreate(BaseModel):
    user_email: str = Field(min_length=3, max_length=320)
    permission: str = Field(default="read", pattern="^read$")


class DocumentPermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    user_id: int
    permission: str
    created_at: datetime


class DocumentChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    chunk_index: int
    content: str
    char_start: int
    char_end: int
    token_start: int
    token_end: int
    source_page: int | None
    source_label: str | None
    embedding_model: str | None


class DocumentSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10_000)
    limit: int = Field(default=5, ge=1, le=20)
    retrieval_strategy: Literal[
        "dense", "lexical", "hybrid", "reranked", "multi_query"
    ] | None = None


class DocumentSearchResult(BaseModel):
    document_id: int
    document_filename: str
    chunk_id: int
    chunk_index: int
    content: str
    source_page: int | None
    source_label: str | None
    score: float
