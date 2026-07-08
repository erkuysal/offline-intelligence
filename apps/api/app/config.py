from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Offline Intelligence Hub API"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000

    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret_key: str = "change-me-in-production"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_minutes: int = 7 * 24 * 60
    document_storage_dir: str = "storage/documents"
    max_upload_size_bytes: int = 5 * 1024 * 1024
    document_chunk_size_chars: int = 2_000
    document_chunk_overlap_chars: int = 200
    llm_backend: str = "fake"
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = "local-default"
    llm_timeout_seconds: float = 60.0
    llm_warmup_enabled: bool = True
    llm_warmup_timeout_seconds: float = 5.0
    llm_warmup_retry_seconds: float = 10.0
    llm_max_total_message_chars: int = 50_000
    llm_max_completion_tokens: int = 2_048
    llm_max_concurrent_requests: int = 1

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
