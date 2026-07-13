# Offline Intelligence Hub Web

Vue 3 frontend for the Offline Intelligence Hub MVP.

## Commands

```bash
npm install
npm run dev
npm run typecheck
npm run test:unit
npm run test:e2e
npm run build
```

The Vite dev server proxies `/api`, `/health`, and `/metrics` to `http://127.0.0.1:8000`.
Set `VITE_API_BASE_URL` when the API is hosted on another origin.

`npm run test:e2e` starts a dedicated API on port `8002` and Vite server on port `5174`.
The API uses `offline_ai_e2e`, isolated document storage, synchronous ingestion, and fake model
providers with enough concurrency for parallel workers. The suite clears its database and stored files before and after every complete run.
Override the ports with `E2E_API_PORT` and `E2E_WEB_PORT`.

## Structure

```text
src/api/          typed FastAPI client
src/components/   layout and reusable UI primitives
src/router/       protected application routes
src/stores/       Pinia stores for session, documents, and system state
src/types/        API response types
src/views/        route-level screens
tests/unit/       Vitest tests
tests/e2e/        Playwright tests
```
