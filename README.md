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
- OpenAI-style chat completions endpoint with a fake local LLM backend

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
llama-server \
  -hf ggml-org/gemma-3-1b-it-GGUF:Q4_K_M \
  --host 127.0.0.1 \
  --port 8080 \
  -c 4096
```

```env
LLM_BACKEND=openai_compatible
LLM_BASE_URL=http://127.0.0.1:8080/v1
LLM_MODEL=ggml-org/gemma-3-1b-it-GGUF:Q4_K_M
LLM_TIMEOUT_SECONDS=60
LLM_MAX_TOTAL_MESSAGE_CHARS=50000
LLM_MAX_COMPLETION_TOKENS=2048
LLM_MAX_CONCURRENT_REQUESTS=1
```

The LLM limits are hardware safety rails. They are intended to prevent accidental oversized prompts, runaway generations, or concurrent CPU-heavy requests on local machines.
LLM request outcomes and latency totals are exposed from `/metrics`.

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
