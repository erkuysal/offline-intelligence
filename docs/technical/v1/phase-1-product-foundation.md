# Technical Vision v1 — Phase 1 Product Foundation

Status: Completed

## Intent

Establish a conventional, testable product foundation before introducing model inference. The API,
identity model, persistence layer, deployment topology, and observability contracts must stand on
their own without AI-specific assumptions.

## System Outcome

- FastAPI application with versioned REST routes and generated API documentation
- PostgreSQL persistence managed through SQLAlchemy and Alembic
- Registration, login, refresh tokens, roles, and protected resources
- Document metadata and local file lifecycle
- Structured logging, health checks, and Prometheus metrics
- Docker Compose development dependencies and automated backend tests
- Vue browser application and single-origin production routing delivered through the later MVP scope

## Architectural Boundaries

- HTTP schemas are distinct from persistence models.
- Schema changes are applied through migrations.
- Authentication and authorization are application services, not UI conventions.
- Health distinguishes process liveness from dependency readiness.
- Configuration comes from explicit environment profiles and contains no committed secrets.

## Implemented Component and Function Map

| Area | Main functions/classes | Used for and why |
| --- | --- | --- |
| Configuration | `Settings`, `get_settings()` | Validates environment-driven limits once and caches the resulting settings object |
| Authentication API | `register_user()`, `login_user()`, `refresh_token()` | Owns credential workflows and emits access/refresh tokens through one contract |
| Password security | `hash_password()`, `verify_password()` | Stores a salted slow hash instead of plaintext or reversible credentials |
| Token security | `create_access_token()`, `create_refresh_token()`, `_decode_token()` | Separates short-lived API access from longer refresh sessions and validates token type |
| Request identity | `get_current_user()`, `require_roles()` | Resolves the bearer subject to an active database user and applies role checks |
| Document storage | `store_upload()`, `delete_stored_file()` | Streams uploads to controlled storage while calculating size and SHA-256 digest |
| Persistence | `get_db()` and SQLAlchemy models | Provides transaction-scoped sessions and explicit relational ownership |
| Operations | health routes, logging middleware, `metrics_registry` | Separates liveness/readiness and records requests without coupling code to Prometheus syntax |

Source entry points include
[`config.py`](../../../apps/api/app/config.py),
[`passwords.py`](../../../apps/api/app/security/passwords.py),
[`tokens.py`](../../../apps/api/app/security/tokens.py), and
[`auth.py`](../../../apps/api/app/dependencies/auth.py).

## Security Calculations

### Password storage

Passwords use PBKDF2-HMAC-SHA256 with a random 16-byte salt and 600,000 iterations:

```text
derived_key = PBKDF2-HMAC-SHA256(password, random_salt, 600000)
stored_value = algorithm $ iterations $ base64(salt) $ base64(derived_key)
```

During verification, the same derivation is repeated and compared with
`hmac.compare_digest()` to avoid a normal early-exit string comparison. The salt prevents equal
passwords from producing equal stored values; the iteration count raises offline guessing cost.

### Session tokens

JWT-like tokens are signed with HMAC-SHA256:

```text
signing_input = base64url(header) + "." + base64url(payload)
signature = HMAC-SHA256(secret, signing_input)
```

The payload contains subject, issued-at time, expiry, unique token ID, and token type. Access and
refresh decoding require the expected type, so a refresh token cannot be used as an API bearer token.
The current default lifetimes are 30 minutes for access and seven days for refresh, configurable per
environment.

### Upload bounds

Uploads are read incrementally rather than loaded wholly into memory. For every byte block:

```text
size = size + len(block)
digest = SHA256(previous_digest_state + block)
```

The request is rejected when cumulative size crosses the configured limit (5 MiB by default). The
digest supports duplicate detection and integrity tracking; it is not treated as authorization.

## Why These Choices

- PostgreSQL transactions are preferable to separate identity/document stores at this scale because
  ownership and metadata changes can commit atomically.
- Alembic makes schema state reviewable and repeatable instead of relying on ORM auto-creation.
- HMAC tokens keep the initial deployment self-contained; rotating or replacing the signing model
  remains possible behind the token functions.
- A fake dependency/runtime path enables deterministic tests without weakening the real contracts.

## Completion Evidence

- [Phase 1 backend ADR](../../adr/0001-phase-1-backend-foundation.md)
- [v0.4.0 integrated acceptance](../../acceptance/v0.4.0.md)
- [Installation and contributor setup](../../installation.md)

## Lasting Responsibility

All later model, retrieval, training, and deployment work inherits this layer's API compatibility,
authorization, migration, observability, and testability requirements.
