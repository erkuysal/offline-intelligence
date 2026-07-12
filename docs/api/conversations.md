# Conversation API Contract

All conversation endpoints require authentication and are owner-only. A conversation belonging
to another user is returned as `404 Conversation not found` rather than revealing its existence.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/chat/conversations` | List the current user's conversations, newest activity first. |
| `GET` | `/api/v1/chat/conversations/{id}` | Read conversation metadata. |
| `GET` | `/api/v1/chat/conversations/{id}/messages` | Read ordered messages, usage, and citations. |
| `DELETE` | `/api/v1/chat/conversations/{id}` | Delete the conversation, messages, and citations. |

Assistant messages expose `model`, `prompt_tokens`, `completion_tokens`, and `total_tokens`.
Each citation includes document and chunk identifiers, filename, page/section label, retrieval
score, character bounds, and the persisted source passage.

Citation passage snapshots remain in storage so conversation records survive document changes.
They are returned only while the requesting conversation owner can still read the cited document.
For a deleted or inaccessible document, `document_accessible` is `false`, `content` is `null`, and
navigation must be disabled. This prevents historical conversations from bypassing current
document authorization.
