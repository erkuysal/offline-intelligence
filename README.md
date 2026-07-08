# Offline Intelligence Hub

Phase 1 backend for an offline/on-premise document intelligence platform.

## Current Capabilities

- FastAPI REST API
- PostgreSQL via Docker Compose
- Redis via Docker Compose
- SQLAlchemy models and Alembic migrations
- User registration and login
- Access and refresh tokens
- Basic RBAC with `user` and `admin` roles
- TXT/PDF document upload with a 5 MB limit
- Document metadata listing, lookup, and deletion
- Local file storage for uploaded documents
- Structured request logging
- Basic `/metrics` endpoint with HTTP and LLM request counters
- Non-streaming LLM token usage tracking
- OpenAI-style chat completions endpoint with a fake local LLM backend
- Streaming chat completions via server-sent events

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

At API startup, a background one-token completion verifies that the model can perform inference. `/health/llm` reports `503` while warming or unavailable and becomes ready after a successful probe; failed probes retry without blocking the rest of the API.
LLM request outcomes and latency totals are exposed from `/metrics`.
Non-streaming completion responses include `usage` when the backend provides token counts; the fake backend returns deterministic estimated counts for tests.

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

Probe the configured backend directly:

```bash
./app.py llm-probe "Explain the project briefly."
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

Run tests:

```bash
./app.py test
```

Run tests inside Docker Compose:

```bash
./app.py test-container
```

This rebuilds the API test image, waits for PostgreSQL and Redis, applies migrations, and runs `pytest` inside the container.

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
