# Offline Intelligence Hub

Phase 1 backend for an offline/on-premise document intelligence platform.

## Current Capabilities

- FastAPI REST API
- PostgreSQL via Docker Compose
- SQLAlchemy models and Alembic migrations
- User registration and login
- Access and refresh tokens
- Basic RBAC with `user` and `admin` roles
- TXT/PDF document upload with a 5 MB limit
- Document metadata listing, lookup, and deletion
- Local file storage for uploaded documents

## Local Setup

Activate the project environment:

```bash
conda activate offline-ai
```

Start PostgreSQL:

```bash
docker compose up -d postgres
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
