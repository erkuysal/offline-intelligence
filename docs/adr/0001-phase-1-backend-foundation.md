# ADR 0001: Phase 1 Backend Foundation

## Status

Accepted

## Context

Phase 1 needs a small, runnable backend that proves the core product loop before adding local LLM or RAG features. The system must run locally, support on-premise deployment assumptions, and be simple to test in both a developer environment and Docker Compose.

## Decision

- Use FastAPI for the REST API.
- Use PostgreSQL as the relational database and SQLAlchemy with Alembic for schema management.
- Use Redis as the cache/queue-ready infrastructure dependency and expose `/health/redis`.
- Use Docker Compose for the API, PostgreSQL, Redis, and containerized test execution.
- Store uploaded TXT/PDF files on local filesystem storage during Phase 1.
- Keep document metadata in PostgreSQL.
- Use JWT access and refresh tokens for authentication.
- Use basic role-based access control with `user` and `admin` roles.
- Keep observability lightweight with structured request logging, `/health`, `/health/db`, `/health/redis`, and `/metrics`.

## Consequences

- The Phase 1 app can be started and tested with local services or Docker Compose.
- The API has enough operational checks for smoke testing and container health checks.
- Local file storage is intentionally simple and can be replaced by object storage or a volume-backed storage service later.
- Redis is available for future background jobs, rate limiting, caching, or task coordination, but Phase 1 only validates connectivity.
- The test suite depends on PostgreSQL and Redis being available; database cleanup fixtures keep repeated runs deterministic.
