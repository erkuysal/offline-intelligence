from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.constants import EMBEDDING_DIMENSIONS
from app.env_files import resolve_env_files


class Settings(BaseSettings):
    app_name: str = "Offline Intelligence Hub API"
    app_version: str = "0.5.0"
    environment: str = "development"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000

    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret_key: str = "change-me-in-production"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_minutes: int = 7 * 24 * 60
    document_storage_dir: str = "var/storage/documents"
    max_upload_size_bytes: int = 5 * 1024 * 1024
    document_ingestion_mode: str = "sync"
    document_ingestion_queue_name: str = "document_ingestion"
    document_ingestion_worker_poll_seconds: int = 5
    document_ingestion_max_attempts: int = 3
    document_chunk_size_chars: int = 2_000
    document_chunk_overlap_chars: int = 200
    embedding_backend: str = "fake"
    embedding_base_url: str = "http://127.0.0.1:8080/v1"
    embedding_model: str = "fake-bow"
    embedding_timeout_seconds: float = 30.0
    embedding_dimensions: int = EMBEDDING_DIMENSIONS
    embedding_reindex_batch_size: int = 32
    rag_retrieval_limit: int = 5
    rag_max_context_chars: int = 12_000
    rag_max_context_chars_per_document: int = Field(default=6_000, ge=1)
    rag_retrieval_strategy: Literal[
        "dense", "lexical", "hybrid", "reranked", "multi_query"
    ] = "dense"
    hybrid_overfetch_multiplier: int = Field(default=3, ge=1, le=20)
    hybrid_max_candidates_per_strategy: int = Field(default=100, ge=1, le=500)
    hybrid_rrf_k: int = Field(default=60, ge=1, le=1_000)
    reranker_backend: str = "disabled"
    reranker_base_url: str = "http://127.0.0.1:8082/v1"
    reranker_model: str = "bge-reranker-v2-m3"
    reranker_model_revision: str = "b5160aeac3c6c8fe7beaaaf04c9e0142826b58d1"
    reranker_timeout_seconds: float = Field(default=30.0, gt=0)
    reranker_candidate_limit: int = Field(default=20, ge=1, le=100)
    query_rewrite_backend: str = "disabled"
    query_rewrite_base_url: str = "http://127.0.0.1:8080/v1"
    query_rewrite_model: str = "ggml-org/gemma-3-1b-it-GGUF:Q4_K_M"
    query_rewrite_model_revision: str = "61333bac858461ec0c309b7baafdc408d7d2c381"
    query_rewrite_timeout_seconds: float = Field(default=10.0, gt=0)
    query_rewrite_max_tokens: int = Field(default=128, ge=16, le=512)
    multi_query_max_generated_variants: int = Field(default=2, ge=0, le=4)
    multi_query_max_query_chars: int = Field(default=500, ge=1, le=2_000)
    multi_query_candidates_per_variant: int = Field(default=10, ge=1, le=50)
    multi_query_max_candidate_observations: int = Field(default=30, ge=1, le=100)
    multi_query_max_pipeline_ms: float = Field(default=2_000.0, gt=0)
    multi_query_rrf_k: int = Field(default=60, ge=1, le=1_000)
    retrieval_run_persistence_enabled: bool = True
    retrieval_run_persist_query_text: bool = False
    retrieval_run_persist_passage_text: bool = False
    retrieval_run_retention_days: int = Field(default=30, ge=1)
    llm_backend: str = "fake"
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = "local-default"
    llm_model_revision: str = "operator-managed"
    llm_adapter_id: str | None = None
    llm_adapter_sha256: str | None = None
    llm_timeout_seconds: float = 60.0
    llm_warmup_enabled: bool = True
    llm_warmup_timeout_seconds: float = 5.0
    llm_warmup_retry_seconds: float = 10.0
    llm_max_total_message_chars: int = 50_000
    llm_max_completion_tokens: int = 2_048
    llm_max_concurrent_requests: int = 1

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=resolve_env_files() or None)  # type: ignore[call-arg]
