# Streaming Chat Contract

`POST /api/v1/chat/completions` returns `text/event-stream` when `stream` is
`true`. Events are UTF-8 SSE frames separated by a blank line. Clients must
parse frames incrementally because network chunks can split any line or frame.

## Events

| Event | Data | Meaning |
| --- | --- | --- |
| `sources` | JSON array of `ChatSource` objects | Optional retrieval sources, emitted before model output. |
| `message` (default) | OpenAI-compatible chat completion chunk | Zero or more token deltas. The event name is omitted on the wire. |
| `complete` | `{conversation_id, model, usage}` | The full exchange and sources have been committed. |
| `error` | `{code, detail, retryable}` | The stream failed and was not persisted. No `complete` event follows. |
| `message` (default) | `[DONE]` | Successful stream terminator, emitted after `complete`. |

The server suppresses the upstream model's `[DONE]` marker until persistence
succeeds. A client should therefore treat `complete` as the authoritative
success result and `[DONE]` as the transport terminator.

## Stable Errors

Errors detected before a response starts use normal HTTP responses. In
particular, concurrency rejection is `429` with `LLM backend is busy`.
Non-streaming model failures remain `503` for unavailable and `504` for timeout.
Once streaming headers have been sent, model failures use `error`:

| Code | Retryable | Meaning |
| --- | --- | --- |
| `llm_timeout` | yes | The model exceeded its configured timeout. |
| `llm_unavailable` | yes | The model connection or service failed. |
| `llm_invalid_response` | no | The model returned an invalid response. |

Client cancellation closes the connection, so no final SSE event can be
delivered. Cancellation does not persist a partial exchange and always releases
the server concurrency slot. The client owns the `cancelled` UI state and may
keep already-rendered text locally.
