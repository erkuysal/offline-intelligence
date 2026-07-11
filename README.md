# Offline Intelligence Hub

Phase 3 backend for an offline/on-premise document intelligence platform.

## Current Capabilities

- FastAPI REST API
- PostgreSQL via Docker Compose
- Redis via Docker Compose
- SQLAlchemy models and Alembic migrations
- User registration and login
- Access and refresh tokens
- Basic RBAC with `user` and `admin` roles
- TXT, PDF, Markdown, and DOCX document upload with a 5 MB limit
- TXT, PDF, Markdown, and DOCX text extraction with persisted source-aware chunks
- Document metadata listing, lookup, and deletion
- Local file storage for uploaded documents
- Structured request logging
- Prometheus `/metrics` endpoint with HTTP and LLM request, latency, concurrency, and token metrics
- Non-streaming and streaming LLM token usage tracking
- OpenAI-style chat completions endpoint with a fake local LLM backend
- Opt-in document retrieval for grounded chat responses with source metadata
- Streaming chat completions via server-sent events

## Product Plans

- [UI engineering plan](docs/ui/README.md)
- [MVP product and release plan](docs/mvp/README.md)
- [Development roadmap](offline-intelligence-hub-roadmap.en.md)

## Local Setup

Activate the project environment:

```bash
conda activate offline-ai
```

Start dependencies:

```bash
docker compose up -d postgres redis
```

Apply migrations:

```bash
./app.py migrate
```

Start the API:

```bash
./app.py runserver
```

The API runs at:

```text
http://127.0.0.1:8000
```

Interactive docs:

```text
http://127.0.0.1:8000/docs
```

## Local LLM

Phase 2 starts with a fake LLM backend so the API and tests run without a model file:

```env
LLM_BACKEND=fake
```

The Phase 2 runtime decision is recorded in
[`docs/adr/0002-phase-2-llm-runtime.md`](docs/adr/0002-phase-2-llm-runtime.md), and current
acceptance evidence is tracked in [`docs/phase-2-acceptance.md`](docs/phase-2-acceptance.md).

To use a local OpenAI-compatible server such as `llama-server`, start it on port `8080` and configure:

```bash
./app.py llm-start
```

```env
LLM_BACKEND=openai_compatible
LLM_BASE_URL=http://127.0.0.1:8080/v1
LLM_MODEL=ggml-org/gemma-3-1b-it-GGUF:Q4_K_M
LLM_TIMEOUT_SECONDS=60
LLM_WARMUP_ENABLED=true
LLM_WARMUP_TIMEOUT_SECONDS=5
LLM_WARMUP_RETRY_SECONDS=10
LLM_MAX_TOTAL_MESSAGE_CHARS=50000
LLM_MAX_COMPLETION_TOKENS=2048
LLM_MAX_CONCURRENT_REQUESTS=1

LLAMA_CPP_BIN=~/tools/llama.cpp/build/bin/llama-server
LLAMA_HOST=127.0.0.1
LLAMA_PORT=8080
LLAMA_MODEL_REPO=ggml-org/gemma-3-1b-it-GGUF:Q4_K_M
LLAMA_MODEL_PATH=
LLAMA_CTX_SIZE=4096
LLAMA_THREADS=
LLAMA_PARALLEL=1
LLAMA_BATCH_SIZE=
LLAMA_UBATCH_SIZE=
LLAMA_GPU_LAYERS=
LLAMA_FLASH_ATTN=
LLAMA_EXTRA_ARGS=
LLAMA_PROFILE=
LLAMA_PROFILE_DIR=scripts/llama_profiles
LLAMA_PID_FILE=/tmp/offline-hub-llama-server.pid
LLAMA_SHUTDOWN_TIMEOUT_SECONDS=15
```

The LLM limits are hardware safety rails. They are intended to prevent accidental oversized prompts, runaway generations, or concurrent CPU-heavy requests on local machines.
The `LLAMA_*` settings control the local `llama-server` process. By default the profile is conservative for WSL CPU use: one parallel slot, a 4096-token context, automatic thread selection, and llama.cpp's default device behavior.
To use a local `.gguf` file instead of Hugging Face download/cache, set `LLAMA_MODEL_PATH=/path/to/model.gguf`; when this is set it takes precedence over `LLAMA_MODEL_REPO`.
`./app.py llm-start` writes `LLAMA_PID_FILE`, removes stale PID files, and exits cleanly when the configured server is already responding. Stop a server launched by this project with:

```bash
./app.py llm-stop
```

Shutdown sends `SIGTERM` first and waits `LLAMA_SHUTDOWN_TIMEOUT_SECONDS` before using `SIGKILL`.

GPU offload is opt-in from this project config. If your llama.cpp build supports CUDA, set `LLAMA_GPU_LAYERS=auto`, `LLAMA_GPU_LAYERS=all`, or a numeric layer count. Verify device visibility with:

```bash
~/tools/llama.cpp/build/bin/llama-server --list-devices
```

For an NVIDIA WSL setup, the practical flow is:

```bash
cd ~/tools/llama.cpp
cmake -B build-cuda -DGGML_CUDA=ON
cmake --build build-cuda --config Release -j "$(nproc)"
```

Then update:

```env
LLAMA_CPP_BIN=~/tools/llama.cpp/build-cuda/bin/llama-server
LLAMA_GPU_LAYERS=auto
```

Check the running server:

```bash
./app.py llm-check
```

There is also a preset for the larger Llama 3.1 8B GPU profile:

```bash
scripts/start_llama_3_1_8b_gpu.sh
```

It maps to:

```bash
~/tools/llama.cpp/build-cuda/bin/llama-server \
  -hf ggml-org/Meta-Llama-3.1-8B-Instruct-Q4_0-GGUF:Q4_0 \
  --host 127.0.0.1 \
  --port 8080 \
  -c 8192 \
  -ngl 99
```

The preset still uses the managed start script underneath, so PID handling, stale-process checks, and already-running detection remain active.

For experimentation, use named runtime profiles. Profiles are simple env files in `scripts/llama_profiles/` and override the base `.env` values:

```bash
./app.py llm-start --profile llama31-8b-9950x-5070
```

The included `llama31-8b-9950x-5070` profile sets:

```env
LLAMA_CPP_BIN=~/tools/llama.cpp/build-cuda/bin/llama-server
LLAMA_MODEL_REPO=ggml-org/Meta-Llama-3.1-8B-Instruct-Q4_0-GGUF:Q4_0
LLAMA_CTX_SIZE=8192
LLAMA_GPU_LAYERS=99
LLAMA_THREADS=16
LLAMA_BATCH_SIZE=2048
LLAMA_FLASH_ATTN=true
```

You can copy that file to create variants such as `llama31-8b-t8.env`, `llama31-8b-b1024.env`, or a CPU-only profile. `LLAMA_EXTRA_ARGS` is available for one-off llama.cpp flags that are not first-class config variables yet.

At API startup, a background one-token completion verifies that the model can perform inference. `/health/llm` reports `503` while warming or unavailable and becomes ready after a successful probe; failed probes retry without blocking the rest of the API.
LLM request outcomes, latency, active requests, rejections, warm-up attempts, and token totals are
exposed in Prometheus format from `/metrics`. A structured diagnostic snapshot remains available
from `/metrics.json`.
Non-streaming completion responses include `usage` when the backend provides token counts.
Streaming requests ask compatible backends for a terminal usage chunk and fall back to estimated
counts when it is absent; the fake backend returns deterministic counts for tests.

The chat endpoint is:

```text
POST /api/v1/chat/completions
```

Example request:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat/completions \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Explain the project briefly."}],"max_tokens":128}'
```

Streaming request:

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/chat/completions \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Explain the project briefly."}],"max_tokens":128,"stream":true}'
```

Ground a completion in the authenticated user's documents:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat/completions \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"When do backups run?"}],"use_documents":true,"retrieval_limit":5}'
```

`document_ids` can restrict retrieval to selected documents. Non-streaming responses include a `sources` list. Streaming responses emit an `event: sources` SSE event before completion chunks when sources were found.

Probe the configured backend directly:

```bash
./app.py llm-probe "Explain the project briefly."
```

## Document Ingestion

Uploaded documents are stored on disk, then ingested into database-backed chunks. The document `status` moves through:

```text
pending -> processing -> ready
```

If extraction fails, the document remains available with `status=failed`, `chunk_count=0`, and `ingestion_error` populated. TXT and Markdown extraction are built in; PDF extraction uses `pypdf`; DOCX extraction uses `python-docx`.

Chunk sizing is controlled by:

```env
DOCUMENT_CHUNK_SIZE_CHARS=2000
DOCUMENT_CHUNK_OVERLAP_CHARS=200
DOCUMENT_INGESTION_MODE=sync
DOCUMENT_INGESTION_QUEUE_NAME=document_ingestion
DOCUMENT_INGESTION_WORKER_POLL_SECONDS=5
EMBEDDING_BACKEND=fake
EMBEDDING_BASE_URL=http://127.0.0.1:8080/v1
EMBEDDING_MODEL=fake-bow
EMBEDDING_DIMENSIONS=768
EMBEDDING_TIMEOUT_SECONDS=30
RAG_RETRIEVAL_LIMIT=5
RAG_MAX_CONTEXT_CHARS=12000
```

List chunks for a document:

```text
GET /api/v1/documents/{document_id}/chunks
```

List immutable upload versions for a document:

```text
GET /api/v1/documents/{document_id}/versions
```

Owners can grant read access to another user by email and list existing grants:

```text
POST /api/v1/documents/{document_id}/permissions
GET  /api/v1/documents/{document_id}/permissions
```

Ready chunks are embedded during ingestion and stored in PostgreSQL as `vector(768)` values with an HNSW cosine index. The default fake embedding provider is deterministic and test-friendly; `EMBEDDING_BACKEND=openai_compatible` can target a local OpenAI-compatible `/embeddings` endpoint.
RAG context is capped separately from user messages so retrieval cannot accidentally overload the local model context.
Chunks include nullable `source_page` and `source_label` metadata. PDF chunks carry page numbers when extractable; Markdown and DOCX chunks carry heading labels when available.
Uploading the same filename and checksum for the same owner is rejected as a duplicate. Uploading the same filename with changed content creates the next document version, replaces chunks, and keeps previous version file metadata for audit/history.
Search and RAG retrieval include documents owned by the current user plus documents explicitly shared with read permission. Deletion and permission management remain owner-only.

Non-streaming chat completions are persisted as conversations with user/assistant messages and assistant source links:

```text
GET /api/v1/chat/conversations
GET /api/v1/chat/conversations/{conversation_id}/messages
```

The Phase 3 pgvector migration backfills existing JSON embeddings only when they already have 768 dimensions. Older incompatible embeddings are marked stale by clearing `embedding_model`; run `./app.py embedding-reindex` after configuring the desired embedding backend.

Set `DOCUMENT_INGESTION_MODE=redis` to return uploads as `pending` and process them from Redis. Start a local worker with:

```bash
./app.py ingestion-worker
```

For Docker Compose, run the API with `DOCUMENT_INGESTION_MODE=redis` and start the worker profile:

```bash
docker compose --profile worker up ingestion-worker
```

### Local semantic embeddings

Run the dedicated EmbeddingGemma server separately from the chat model:

```bash
./app.py embedding-start
```

It uses port `8081` by default and has independent CPU, GPU, batch, model, PID, and shutdown settings under `EMBEDDING_SERVER_*`. In another terminal, verify it:

```bash
./app.py embedding-check
```

Configure the API to use it:

```env
EMBEDDING_BACKEND=openai_compatible
EMBEDDING_BASE_URL=http://127.0.0.1:8081/v1
EMBEDDING_MODEL=embeddinggemma-300m
EMBEDDING_DIMENSIONS=768
```

Restart the API after changing `.env`, then replace vectors generated by the fake provider:

```bash
./app.py embedding-reindex
```

For an incremental pass that only processes missing vectors or chunks embedded with another model:

```bash
./app.py embedding-reindex --stale-only
```

Search only considers vectors produced by the currently configured embedding model, preventing incompatible vector dimensions from being mixed. Stop the dedicated server gracefully with:

```bash
./app.py embedding-stop
```

Search over embedded chunks:

```text
POST /api/v1/documents/search
```

```json
{
  "query": "backup policy",
  "limit": 5
}
```

## Smoke Test

With the API running, execute:

```bash
./app.py smoke
```

The smoke test performs a real HTTP flow:

- health check
- database health check
- redis health check
- llm health check
- metrics
- user registration
- login
- token refresh
- `/users/me`
- chat completion
- TXT document upload
- document listing
- document deletion

## Development Checks

Run lint:

```bash
./app.py lint
```

Run static type checks:

```bash
./app.py typecheck
```

Run tests:

```bash
./app.py test
```

The local test command requires PostgreSQL and Redis to be running. It creates the isolated
`offline_ai_test` database when needed, applies migrations, forces the fake LLM and embedding
backends, and then runs `pytest`. By default the test database URL is derived from `DATABASE_URL`;
set `TEST_DATABASE_URL` and `TEST_DATABASE_ADMIN_URL` to override it. The test fixtures and
database preparation script both refuse non-test database names.
Pass pytest options after `--`, for example `./app.py test -- -k chat`.

Run tests inside Docker Compose:

```bash
./app.py test-container
```

This rebuilds the API test image and runs the same isolated database preparation, migrations,
and test suite inside the container.

## Docker Compose

Build and start the API with PostgreSQL and Redis:

```bash
docker compose up --build api
```

The API container waits for PostgreSQL and Redis, applies Alembic migrations, and then starts FastAPI on:

```text
http://127.0.0.1:8000
```

Run the same smoke test against the containerized API:

```bash
./app.py smoke
```
