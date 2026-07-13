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

To test the built application through the production reverse proxy, start the production Compose
stack with `config/env/test.env`, then run:

```bash
npm run test:e2e:production
```

The production suite targets `http://127.0.0.1:18081` by default. Override it with
`E2E_PRODUCTION_BASE_URL` when the reverse proxy is exposed on a different origin.

Run the primary workflow slowly in a visible browser without changing normal test timing:

```bash
npm run test:e2e:demo
```

Generate and inspect an HTML report, or use Playwright's interactive test runner:

```bash
npm run test:e2e:report
npm run test:e2e:report:open
npm run test:e2e:ui
```

Real-model acceptance is deliberately opt-in. Start the local LLM and embedding servers first,
then run the single-worker acceptance flow:

```bash
npm run test:e2e:real
```

This switches the isolated API to `openai_compatible` backends at
`http://127.0.0.1:8080/v1` and `http://127.0.0.1:8081/v1`. Override those endpoints with
`LLM_BASE_URL` and `EMBEDDING_BASE_URL`. Normal `test:e2e`, report, UI, and demo commands always
use deterministic fake providers unless `E2E_MODEL_MODE=real` is explicitly supplied.

## Production Image

Build the Vue application into its Nginx runtime image from the repository root:

```bash
docker build -f apps/web/Dockerfile -t offline-intelligence-hub-web .
```

The image serves the SPA on port `80`, exposes `/web-health` for its container health check, and
proxies `/api`, `/health`, and `/metrics` to the `api:8000` service. API buffering is disabled so
streaming chat events are delivered immediately. The production Compose topology supplies the
`api` service name; it is added in the next infrastructure slice.

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
