# UI Engineering Plan

## Status

In development on `feat/mvp-ui`. The first integrated UI is targeted for `v0.4.0`.

## Purpose

The UI turns the existing API into a usable local document-intelligence application. It is an
operational product interface, not a marketing site. A user should be able to authenticate,
manage documents, ask grounded questions, inspect sources, and understand service failures
without using curl or the OpenAPI console.

## Technical Direction

- Vue 3 with TypeScript
- Vite-based development and production builds
- Vue Router for application routes
- Pinia for session and shared application state
- SCSS for application styles, compiled by Vite
- A small typed API client aligned with the FastAPI OpenAPI contract
- Fetch streaming for POST-based chat completions
- Playwright for browser-level workflows
- Component and unit tests for state, API, and interaction behavior

Dependency versions will be pinned when the frontend is scaffolded. New dependencies require a
clear product or maintenance benefit.

Global styles live in `src/styles/base.scss`. New styles should use SCSS rather than plain CSS;
keep nesting shallow and colocate feature-specific rules when a view grows beyond the shared
foundation.

## Repository Location

The frontend lives at `apps/web/` in the monorepo. Parallel development uses the
`feat/mvp-ui` branch in a sibling Git worktree:

```text
offline-intelligence-hub/     root branch, backend and integration
offline-intelligence-hub-ui/  feat/mvp-ui branch, frontend
```

Proposed structure:

```text
apps/web/
├── src/
│   ├── api/
│   ├── components/
│   ├── features/
│   │   ├── auth/
│   │   ├── chat/
│   │   ├── documents/
│   │   └── system/
│   ├── router/
│   ├── stores/
│   ├── styles/
│   ├── views/
│   ├── App.vue
│   └── main.ts
├── tests/
├── Dockerfile
├── index.html
├── package.json
└── vite.config.ts
```

## Application Routes

| Route | Purpose | Authentication |
|---|---|---|
| `/login` | Start a user session | Public |
| `/register` | Create a local account | Public |
| `/documents` | Upload and manage documents | Required |
| `/documents/:id` | Inspect metadata, status, and chunks | Required |
| `/chat` | Ask document-grounded questions | Required |
| `/system` | Inspect API, database, Redis, LLM, and embedding health | Required |

Unknown routes redirect to the appropriate authenticated or public start screen.

## Primary Workflows

### Authentication

1. Register or log in.
2. Store the access token in memory and session storage for the MVP.
3. Refresh the access token once after an authentication failure.
4. Clear all credentials and return to `/login` when refresh fails or the user logs out.

The current API returns refresh tokens to JavaScript. Moving refresh credentials to secure,
HTTP-only cookies should be evaluated before a broader multi-user deployment.

### Documents

1. Select or drop a supported file.
2. Validate visible size and format constraints before upload.
3. Show upload progress and the resulting ingestion state.
4. Poll or refresh while a document is `pending` or `processing`.
5. Show chunk count or a useful ingestion error when processing finishes.
6. Allow inspection and deletion with confirmation.

The UI must represent `pending`, `processing`, `ready`, and `failed` explicitly. A failed
document must never look ready for retrieval.

### Grounded Chat

1. Enter a question.
2. Enable or disable document grounding.
3. Optionally select specific documents.
4. Stream the assistant response from the POST completion endpoint.
5. Support stopping the active response.
6. Render sources separately from generated answer text.
7. Open the cited document passage from a source action.

The client parses normal SSE `data` messages, the custom `sources` event, terminal usage data,
`[DONE]`, and structured error events. It must tolerate chunks split across network reads.

## Current API Contract

Initial UI work can use these existing endpoints:

```text
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
GET    /api/v1/users/me

POST   /api/v1/documents
GET    /api/v1/documents
GET    /api/v1/documents/{id}
GET    /api/v1/documents/{id}/chunks
POST   /api/v1/documents/search
DELETE /api/v1/documents/{id}

POST   /api/v1/chat/completions

GET    /health
GET    /health/db
GET    /health/redis
GET    /health/llm
GET    /metrics
GET    /metrics.json
```

Phase 3 endpoints for asynchronous ingestion, conversations, and richer source metadata will be
adopted behind the typed API layer rather than accessed directly from view components.

## UX Requirements

- The authenticated application opens on the working interface, not a landing page.
- Navigation remains predictable between documents, chat, and system status.
- Loading, empty, success, busy, timeout, offline, validation, and permission states are explicit.
- Destructive actions require confirmation and cannot be triggered accidentally.
- Keyboard focus, labels, contrast, and reduced-motion preferences are respected.
- Layouts remain usable on mobile and desktop without text or controls overlapping.
- Operational tools use restrained styling optimized for scanning and repeated work.
- Icon buttons use the selected icon library and include accessible names and tooltips.

## State Boundaries

- Session store: identity, tokens, refresh lifecycle
- Document store: collection, selection, upload and ingestion status
- Chat store: messages, current stream, selected documents, sources, cancellation
- System store: service health and model readiness

Server-owned data should be refetched after mutations. Stores must not become a second database.

## Error Handling

| Condition | UI behavior |
|---|---|
| `401` | Refresh once, then return to login |
| `403` | Explain that the action is not permitted |
| `404` | Remove stale resource state and return to its list |
| `413` | Show configured upload or model-input limit |
| `429` | Show the model as busy and allow retry |
| `502/503/504` | Identify unavailable, invalid, or timed-out service |
| Stream error event | Preserve partial output and show terminal error state |
| Network failure | Keep recoverable local input and expose retry |

## Testing Strategy

- Unit tests for token refresh, stream parsing, error mapping, and store transitions
- Component tests for forms, document states, source display, and cancellation
- Contract tests using representative FastAPI responses and SSE fixtures
- Playwright tests for register/login, upload/delete, grounded streaming chat, and session expiry
- Responsive screenshots at desktop and mobile viewports
- Production image build and reverse-proxy smoke test in Docker Compose

Streaming browser checks are intentionally split by responsibility:

```bash
# Deterministic timed chunks, cancellation, filtering, and service failures
npx playwright test tests/e2e/chat-streaming.mock.spec.ts --workers=1

# Live API, retrieval, and local-model acceptance
npx playwright test tests/e2e/user-flow.spec.ts --workers=1

# Conversation persistence, citation navigation, deletion, and owner isolation
npx playwright test tests/e2e/conversations.acceptance.spec.ts --workers=1
```

The mocked suite replaces only the browser chat request. Authentication remains real, and its
fetch override is scoped to each Playwright page so it cannot leak into the acceptance workflow.
The conversation acceptance suite requires the current branch API and migrations. Set
`PACKAGE4_API_BASE_URL` when validating against an isolated API port.

## UI Definition of Done

- Authentication, document management, grounded streaming chat, sources, and service status work
  without direct API tooling.
- All expected loading and error states are implemented.
- Browser tests cover the primary workflow.
- The production frontend is served through the MVP reverse proxy.
- The UI works against the Phase 3 API from a clean Docker Compose environment.
- Setup, development, testing, and deployment commands are documented.
