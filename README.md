# Offline Intelligence Hub

`v0.4.0` browser MVP for an offline/on-premise document intelligence platform.

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
- PostgreSQL lexical retrieval strategy with indexed content/filename search and evaluation mode
- Selectable dense, lexical, and reciprocal-rank-fused hybrid retrieval modes
- Streaming chat completions via server-sent events
- Vue 3 browser client with protected authentication, document, chat, conversation, and health routes
- Inspectable persisted citations and conversation history
- Nginx single-origin production routing and deterministic Playwright coverage

## Product Plans

- [Installation and contributor setup](docs/installation.md)
- [Retrieval evaluation](evaluation/README.md)
- [Retrieval observability and retention](docs/api/retrieval-observability.md)
- [UI engineering plan](docs/ui/README.md)
- [MVP product and release plan](docs/mvp/README.md)
- [v0.4.0 acceptance record](docs/acceptance/v0.4.0.md)
- [Development roadmap](docs/roadmap.en.md)

## Local Setup

For a new checkout, install all backend and frontend dependencies with:

```bash
./scripts/setup.sh
```

Use `./scripts/setup.sh --with-browser` when the checkout will run Playwright tests. See the
[installation guide](docs/installation.md) for prerequisites, setup variants, and troubleshooting.
The installer begins with an Interactive/Automatic mode choice, with Interactive selected by
default. Both modes show the complete installation plan; use `--dry-run` to inspect the same
commands without making changes.

Runtime configuration is split by purpose:

- `config/env/dev.env` is loaded by normal backend and local model commands.
- `config/env/test.env` is loaded by `./manage.py test` and can drive deterministic production Compose checks.
- `config/env/e2e.env` is loaded by browser-test setup and cleanup commands.
- `config/env/prod.env` is operator-managed, ignored by Git, and used explicitly by production Compose.

For development, an existing untracked `config/env/local.env` is loaded after
`config/env/dev.env` as a local override. It also remains the fallback when a selected profile
file is absent. Override any
command with `./manage.py --env-file path/to/file <command>` or set `APP_ENV_FILE` for direct Python
and model scripts. Environment variables already exported by the caller take precedence over file
values.

Activate the project environment:

```bash
conda activate offline-ai
```

Start dependencies:

```bash
docker compose -f deploy/compose.yaml up -d postgres redis
```

Apply migrations:

```bash
./manage.py migrate
```

Start the API:

```bash
./manage.py runserver
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
acceptance evidence is tracked in [`docs/acceptance/phase-2.md`](docs/acceptance/phase-2.md).

To use a local OpenAI-compatible server such as `llama-server`, start it on port `8080` and configure:

```bash
./manage.py llm-start
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
LLAMA_PROFILE_DIR=config/models
LLAMA_PID_FILE=var/run/llm.pid
LLAMA_SHUTDOWN_TIMEOUT_SECONDS=15
```

The LLM limits are hardware safety rails. They are intended to prevent accidental oversized prompts, runaway generations, or concurrent CPU-heavy requests on local machines.
The `LLAMA_*` settings control the local `llama-server` process. By default the profile is conservative for WSL CPU use: one parallel slot, a 4096-token context, automatic thread selection, and llama.cpp's default device behavior.
To use a local `.gguf` file instead of Hugging Face download/cache, set `LLAMA_MODEL_PATH=/path/to/model.gguf`; when this is set it takes precedence over `LLAMA_MODEL_REPO`.
`./manage.py llm-start` writes `LLAMA_PID_FILE`, removes stale PID files, and exits cleanly when the configured server is already responding. Stop a server launched by this project with:

```bash
./manage.py llm-stop
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
./manage.py llm-check
```

There is also a preset for the larger Llama 3.1 8B GPU profile:

```bash
scripts/models/start-llama31-gpu.sh
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

For experimentation, use named runtime profiles. Profiles are simple env files in `config/models/`
and override the base development environment:

```bash
./manage.py llm-start --profile llama31-8b-9950x-5070
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
  -d '{"messages":[{"role":"user","content":"When do backups run?"}],"use_documents":true,"retrieval_limit":5,"retrieval_strategy":"dense"}'
```

`document_ids` can restrict retrieval to selected documents. `retrieval_strategy` accepts `dense`,
`lexical`, or `hybrid`; the configured default remains `dense`. Non-streaming responses include a
`sources` list. Streaming responses emit an `event: sources` SSE event before completion chunks when
sources were found.

Probe the configured backend directly:

```bash
./manage.py llm-probe "Explain the project briefly."
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
DOCUMENT_INGESTION_MODE=redis
DOCUMENT_INGESTION_QUEUE_NAME=document_ingestion
DOCUMENT_INGESTION_WORKER_POLL_SECONDS=5
DOCUMENT_INGESTION_MAX_ATTEMPTS=3
EMBEDDING_BACKEND=fake
EMBEDDING_BASE_URL=http://127.0.0.1:8080/v1
EMBEDDING_MODEL=fake-bow
EMBEDDING_DIMENSIONS=768
EMBEDDING_TIMEOUT_SECONDS=30
RAG_RETRIEVAL_LIMIT=5
RAG_MAX_CONTEXT_CHARS=12000
RAG_MAX_CONTEXT_CHARS_PER_DOCUMENT=6000
```

List chunks for a document:

```text
GET /api/v1/documents/{document_id}/chunks
```

List immutable upload versions for a document:

```text
GET /api/v1/documents/{document_id}/versions
```

Owners can rebuild extraction, chunks, and embeddings for an existing document:

```text
POST /api/v1/documents/{document_id}/reindex
```

Redis mode returns `202` with a pending document; synchronous test mode completes the rebuild
before returning.

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

The Phase 3 pgvector migration backfills existing JSON embeddings only when they already have 768 dimensions. Older incompatible embeddings are marked stale by clearing `embedding_model`; run `./manage.py embedding-reindex` after configuring the desired embedding backend.

Redis ingestion is the default application mode. Uploads return as `pending` and are processed by
a worker. Use `DOCUMENT_INGESTION_MODE=sync` only for focused development or tests. Start a local
worker with:

```bash
./manage.py ingestion-worker
```

The worker reserves jobs in a processing list, acknowledges successful or terminal jobs, recovers
interrupted reservations on startup, and retries unexpected failures up to
`DOCUMENT_INGESTION_MAX_ATTEMPTS`.

For Docker Compose, start the API and worker profile together:

```bash
docker compose -f deploy/compose.yaml --profile worker up -d api ingestion-worker
```

### Local semantic embeddings

Run the dedicated EmbeddingGemma server separately from the chat model:

```bash
./manage.py embedding-start
```

It uses port `8081` by default and has independent CPU, GPU, batch, model, PID, and shutdown settings under `EMBEDDING_SERVER_*`. In another terminal, verify it:

```bash
./manage.py embedding-check
```

Configure the API to use it:

```env
EMBEDDING_BACKEND=openai_compatible
EMBEDDING_BASE_URL=http://127.0.0.1:8081/v1
EMBEDDING_MODEL=embeddinggemma-300m
EMBEDDING_DIMENSIONS=768
```

Restart the API after changing `config/env/local.env`, then replace vectors generated by the fake provider:

```bash
./manage.py embedding-reindex
```

For an incremental pass that only processes missing vectors or chunks embedded with another model:

```bash
./manage.py embedding-reindex --stale-only
```

Search only considers vectors produced by the currently configured embedding model, preventing incompatible vector dimensions from being mixed. Stop the dedicated server gracefully with:

```bash
./manage.py embedding-stop
```

### Optional local reranking

The explicit `reranked` strategy reranks at most 20 hybrid candidates with the pinned multilingual
`bge-reranker-v2-m3` model. Start and verify its dedicated llama.cpp server:

```bash
./manage.py reranker-start
./manage.py reranker-check
```

Then configure the API and select `retrieval_strategy: "reranked"` per request:

```env
RERANKER_BACKEND=openai_compatible
RERANKER_BASE_URL=http://127.0.0.1:8082/v1
RERANKER_MODEL=bge-reranker-v2-m3
RERANKER_MODEL_REVISION=b5160aeac3c6c8fe7beaaaf04c9e0142826b58d1
RERANKER_CANDIDATE_LIMIT=20
```

If the server is disabled, unavailable, or returns an invalid response, retrieval keeps the fused
hybrid order. Dense remains the default because the accepted reranker evaluation found no quality
gain and substantially higher latency. Stop the server with `./manage.py reranker-stop`.

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

Chat retrieval and direct document search store privacy-safe diagnostics with a configurable
retention period. Raw query and passage text are disabled by default. See the
[retrieval observability guide](docs/api/retrieval-observability.md), and periodically remove
expired records with:

```bash
./manage.py retrieval-cleanup
```

## Smoke Test

With the API running, execute:

```bash
./manage.py smoke
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
./manage.py lint
```

Run static type checks:

```bash
./manage.py typecheck
```

Run tests:

```bash
./manage.py test
```

The local test command requires PostgreSQL and Redis to be running. It creates the isolated
`offline_ai_test` database when needed, applies migrations, forces the fake LLM and embedding
backends, and then runs `pytest`. By default the test database URL is derived from `DATABASE_URL`;
set `TEST_DATABASE_URL` and `TEST_DATABASE_ADMIN_URL` to override it. The test fixtures and
database preparation script both refuse non-test database names.
Pass pytest options after `--`, for example `./manage.py test -- -k chat`.

Prepare the isolated browser-test database and document storage before starting its API:

```bash
./manage.py e2e-setup
```

The E2E environment uses `offline_ai_e2e`, synchronous ingestion, and deterministic fake LLM
and embedding providers by default. Clear all browser-test rows and uploaded files with:

```bash
./manage.py e2e-cleanup
```

Both commands refuse database names without the `_e2e` suffix and storage paths outside
`/tmp/offline-intelligence-hub-e2e`. Override the defaults with `E2E_DATABASE_URL`,
`E2E_DATABASE_ADMIN_URL`, `E2E_DOCUMENT_STORAGE_ROOT`, and `E2E_DOCUMENT_STORAGE_DIR`; a custom
storage directory must remain beneath its configured E2E storage root.

Run tests inside Docker Compose:

```bash
./manage.py test-container
```

This rebuilds the API test image and runs the same isolated database preparation, migrations,
and test suite inside the container.

Run the frontend and deterministic browser release gates:

```bash
cd apps/web
npm ci
npm run typecheck
npm run test:unit
npm run build
npm run test:e2e
```

With local OpenAI-compatible chat and embedding servers listening on ports `8080` and `8081`, run
the opt-in real-model workflow with `npm run test:e2e:real`. Exact accepted model identifiers and
results are recorded in [`docs/acceptance/v0.4.0.md`](docs/acceptance/v0.4.0.md).

## Docker Compose

Build and start the API with PostgreSQL and Redis:

```bash
docker compose -f deploy/compose.yaml up --build api
```

The API container waits for PostgreSQL and Redis, applies Alembic migrations, and then starts FastAPI on:

```text
http://127.0.0.1:8000
```

Run the same smoke test against the containerized API:

```bash
./manage.py smoke
```

### Production web stack

Create the production environment file and replace both placeholder secrets before startup:

```bash
cp config/env/prod.example.env config/env/prod.env
docker compose --env-file config/env/prod.env -f deploy/compose.prod.yaml up --build -d --wait
```

The production stack publishes the Vue and Nginx application on `WEB_PORT` (port `3000` by
default). FastAPI, the ingestion worker, PostgreSQL, and Redis are reachable only through the
Compose network. The production example also starts internal CPU model services; switch
`COMPOSE_PROFILES` to `models-gpu` for NVIDIA acceleration. Model paths, image pins, hardware
requirements, and startup diagnostics are documented in
[`docs/mvp/model-runtime.md`](docs/mvp/model-runtime.md). The Compose file does not publish
model-server ports.

PostgreSQL data, uploaded documents, and the Redis ingestion queue use the named
`postgres_data`, `api_storage`, and `redis_data` volumes under the
`offline-intelligence-hub-production` Compose project. Containers restart automatically unless
an operator explicitly stops them. A normal production Compose `down` retains these volumes;
adding `--volumes` permanently deletes application data.

Inspect or stop this stack with the same file and environment arguments:

```bash
docker compose --env-file config/env/prod.env -f deploy/compose.prod.yaml ps
docker compose --env-file config/env/prod.env -f deploy/compose.prod.yaml down
```

After the stack is healthy, validate the built browser application through the reverse proxy:

```bash
cd apps/web
E2E_PRODUCTION_BASE_URL=http://127.0.0.1:${WEB_PORT:-3000} npm run test:e2e:production
```
