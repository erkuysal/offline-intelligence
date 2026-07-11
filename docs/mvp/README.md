# MVP Product and Release Plan

## Status

The Phase 3 backend was released as `v0.3.0`. The integrated browser MVP is now planned for
`v0.4.0`. Implementation is tracked in the [v0.4.0 MVP task list](v0.4.0-task-list.md).

## Product Definition

The Offline Intelligence Hub MVP is a self-hosted web application that lets a user upload
internal documents and ask questions whose answers include inspectable sources. Core inference,
embedding, storage, and retrieval run locally without cloud AI APIs.

The MVP validates one complete product loop:

```text
Register -> Upload -> Ingest -> Ask -> Stream answer -> Inspect sources
```

## Target User

The initial user is a technical professional or small internal team that needs to search private
TXT or PDF material on a workstation or on-premise server. The operator is comfortable starting
Docker Compose but should not need to use curl, SQL, or model-server commands for normal use.

## MVP Scope

### User Capabilities

- Register, log in, refresh a session, and log out
- Upload supported documents with visible limits and progress
- Observe ingestion progress and failures
- List, inspect, and delete owned documents
- Ask ungrounded or document-grounded questions
- Limit retrieval to selected documents
- Receive streaming responses and stop generation
- Inspect source documents, chunks, and relevance metadata
- View system and model readiness

### Platform Capabilities

- FastAPI API with JWT authentication and owner isolation
- PostgreSQL with `pgvector` database-native similarity retrieval
- Redis-backed ingestion worker
- Local filesystem document storage on a persistent volume
- Local OpenAI-compatible LLM and embedding servers
- Prometheus-compatible application, LLM, ingestion, and retrieval metrics
- Vue production client behind a single reverse-proxy origin
- Docker Compose deployment with health checks and persistent volumes

## Explicit Non-Goals

The following work must not delay the MVP:

- LoRA or PEFT training
- Hybrid search, reranking, and formal RAG evaluation
- Organization and complex sharing administration
- Desktop application packaging
- Native C acceleration
- Full air-gapped release bundles and offline installers
- High-availability or multi-node deployment
- Public internet hosting

These remain later roadmap phases.

## Runtime Architecture

```text
Browser
  -> Reverse Proxy
      -> Vue static application
      -> FastAPI /api and health endpoints
          -> PostgreSQL + pgvector
          -> Redis
          -> Ingestion worker
              -> Local embedding server
          -> Local llama.cpp LLM server
```

The reverse proxy exposes one user-facing origin. Internal databases, queues, and model services
are not exposed publicly in the production Compose profile.

## Delivery Tracks

### Backend Track: Phase 3

1. Replace JSON embeddings and Python scoring with `pgvector` retrieval.
2. Introduce asynchronous, idempotent ingestion jobs.
3. Improve extraction, cleaning, chunk metadata, and supported formats.
4. Add document lifecycle, reindexing, and permission-aware retrieval.
5. Add conversation persistence and retrieval observability.

### UI Track: `feat/mvp-ui`

1. Scaffold the Vue application and production build.
2. Implement authentication and protected routing.
3. Implement document upload, status, list, details, and deletion.
4. Implement grounded streaming chat, cancellation, and sources.
5. Implement system health and actionable failure states.
6. Add browser tests and production container integration.

### Integration Track

1. Merge stable UI slices into the main repository.
2. Add reverse proxy and one-origin API configuration.
3. Run backend, frontend, browser, and smoke suites in Compose.
4. Validate clean installation and persistent restart behavior.

## Release Milestones

### M1: UI Foundation

- Application shell, routing, session handling, and typed API boundary
- Mocked document and chat workflows
- Frontend lint, type-check, unit-test, and build commands

### M2: Vector RAG Backend

- `pgvector` migration, vector index, database retrieval, and reindex path
- Real local embedding acceptance
- Retrieval isolation and performance tests

### M3: Integrated Alpha

- UI connected to authentication, documents, chat, sources, and health APIs
- Streaming and cancellation verified in a browser
- Asynchronous ingestion states visible end to end

### M4: `v0.4.0` MVP

- Single-origin production Compose deployment
- Complete automated and manual acceptance suite
- Clean setup and restart documentation
- Release notes, checksums for model/config inputs, and known limitations

## Functional Acceptance Criteria

- A new user can register and log in from the browser.
- The user can upload TXT and PDF documents within configured limits.
- Upload returns promptly and ingestion reaches `ready` or a visible `failed` state.
- Retrieval executes in PostgreSQL with owner and document filters.
- A grounded question returns a streamed answer with at least one inspectable source when relevant.
- The user can stop generation and submit another request afterward.
- Another user cannot list, retrieve, cite, or delete the first user's documents.
- Documents and metadata survive a Compose restart.
- Deleting a document removes its stored file, chunks, embeddings, and retrieval visibility.

## Operational Acceptance Criteria

- A documented command starts the complete application from a clean environment.
- API, frontend, PostgreSQL, Redis, worker, LLM, and embedding services have health signals.
- Startup failures and missing model files produce actionable operator messages.
- Limits prevent oversized uploads, prompts, completions, and uncontrolled model concurrency.
- Metrics expose HTTP, LLM, ingestion, embedding, and retrieval outcomes and latency.
- Backup requirements and persistent volume locations are documented.
- No cloud AI API or external telemetry is required at runtime.

## Security Baseline

- Passwords remain hashed and secrets are supplied through configuration.
- Authorization filters are applied inside document and retrieval queries.
- Uploaded filenames cannot control storage paths.
- File type, size, and extraction behavior are validated defensively.
- Document context is treated as untrusted data, not system instructions.
- Browser credentials are cleared on logout and failed refresh.
- Production containers avoid unnecessary host ports and privileges.

This baseline is appropriate for a local/on-premise MVP, not an unrestricted public deployment.

## Product Success Signals

- A first-time operator can start the application using only the documentation.
- A user can complete the primary product loop without API tooling.
- Answers consistently expose sources that can be inspected in the UI.
- Failed ingestion and unavailable model states are understandable and recoverable.
- Retrieval remains responsive on the documented MVP corpus size.
- The integrated suite can recreate and verify the deployment deterministically.

## MVP Definition of Done

`v0.4.0` is ready when all functional and operational acceptance criteria pass, the primary
browser workflow is covered by Playwright, the Compose deployment works from clean volumes, and
known limitations are recorded. Desktop packaging and formal air-gapped distribution are
separate follow-up releases rather than MVP blockers.
