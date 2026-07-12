# Operational Health Contract

Health endpoints return one stable JSON shape for both `200` and `503` responses:

```json
{
  "service": "redis",
  "status": "unavailable",
  "detail": "Redis connection failed",
  "code": "redis_unavailable",
  "checked_at": "2026-07-13T00:00:00Z",
  "metadata": {}
}
```

`status` is one of `healthy`, `degraded`, `unavailable`, or `disabled`. `detail` and `code` are
safe for display. Raw exception messages, credentials, connection strings, and upstream response
bodies are never returned.

| Endpoint | Service |
| --- | --- |
| `/health` | API process |
| `/health/db` | PostgreSQL |
| `/health/redis` | Redis |
| `/health/llm` | LLM readiness |
| `/health/embedding` | Embedding provider and dimensions |
| `/health/worker` | Synchronous ingestion or Redis queue reachability |
| `/health/runtime` | Safe limits and model identities |

Redis queue reachability does not prove that an external ingestion worker is alive. Until worker
heartbeats are implemented, Redis ingestion mode therefore reports `degraded` with
`worker_heartbeat_unavailable` even when the queue is reachable.

The runtime response exposes upload, prompt, completion, and concurrency limits plus model names
and embedding dimensions. It does not expose paths, secrets, tokens, or backend URLs.
