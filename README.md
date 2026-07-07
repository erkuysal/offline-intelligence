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
- Basic `/metrics` endpoint

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

## Smoke Test

With the API running, execute:

```bash
./app.py smoke
```

The smoke test performs a real HTTP flow:

- health check
- database health check
- redis health check
- metrics
- user registration
- login
- token refresh
- `/users/me`
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
