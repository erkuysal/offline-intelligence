# Vision 0 — Air-Gapped LLM Extraction Architecture (AGLEA)

Status: Proposed optional deployment topology; not implemented or accepted

## Purpose

AGLEA is a high-isolation deployment option for LLM-backed extraction. It separates the
network-facing request boundary from the environment that can access sensitive local data and run
model inference. The two sides exchange bounded, authenticated JSON envelopes through a filesystem
dead drop; they never communicate over TCP or UDP.

This topology complements rather than replaces the current Offline Intelligence Hub architecture.
The accepted v0.5 runtime uses internal Docker networks between FastAPI, data services, and local
inference. AGLEA is intended for deployments where the inference and sensitive-data boundary must
have no routable network interface at all.

The initial design favors isolation, auditability, and recoverability over streaming responses and
maximum throughput.

## Topology and Trust Zones

```text
Client
  │ HTTPS
  ▼
Zone A: Online Gateway
  authentication · authorization · validation · job registry
  │
  │ authenticated, versioned files
  ▼
Zone B: Shared Volume
  /bridge/requests/   /bridge/processing/
  /bridge/responses/ /bridge/failed/
  │
  │ atomic claim and commit
  ▼
Zone C: Offline Engine
  request validation · authorized context loading · local inference
  no routable network interface
```

### Zone A — Online Gateway

The Gateway owns the public HTTP contract and the caller's security context. It:

- terminates HTTPS and validates authentication credentials;
- authorizes the requested operation and data scope before creating a job;
- normalizes and bounds user-controlled input;
- assigns a server-generated request ID and records job ownership;
- writes authenticated request envelopes to the dead drop;
- observes authenticated terminal responses and exposes them only to the owning caller; and
- applies admission control, deadlines, retention, and safe error translation.

The Gateway must not have direct access to the Offline Engine, its model process, or unrestricted
sensitive datasets. A filename or caller-supplied request ID is never treated as authorization.

### Zone B — Shared Volume

The bridge is a data-only IPC boundary. It is one filesystem so that renames between its staging
and committed locations are atomic. Its mounted paths use restricted service identities and, where
supported, `noexec`, `nodev`, and `nosuid` options. Only regular files are accepted; executables are
never launched from the bridge.

The logical directories are:

| Directory | Purpose |
| --- | --- |
| `/bridge/requests/` | Complete requests waiting to be claimed |
| `/bridge/processing/` | Requests atomically claimed by an engine worker |
| `/bridge/responses/` | Complete terminal response envelopes |
| `/bridge/failed/` | Quarantined malformed or unauthenticated artifacts and bounded diagnostics |

Gateway and Engine mounts should expose only the subpaths and permissions each service needs.
Host ownership, groups, and ACLs must be tested as part of deployment. Cryptographic envelope
verification remains mandatory because filesystem write permission alone cannot establish who
created a message.

### Zone C — Offline Engine

The Offline Engine continuously reconciles the request directory, claims work, loads authorized
local context, runs inference, and commits a terminal response. It:

- runs as a non-root identity with dropped capabilities and a read-only root filesystem;
- has no routable network interface and performs no runtime downloads or telemetry;
- mounts model artifacts and approved local datasets read-only;
- validates envelope authenticity, schema version, bounds, authorization scope, and deadline;
- resolves only allowlisted dataset identifiers, never arbitrary paths supplied in a prompt;
- treats source documents and prompt content as untrusted data; and
- writes the minimum response required by the extraction contract.

An embedded model runtime or a model server reachable only inside Zone C may be used. For example,
`llama.cpp`, Ollama, or vLLM can run in the same isolated environment, but exposing the model
server outside that boundary would violate this topology.

## Public Job Contract

Long-running inference is represented as an asynchronous job rather than a held HTTP connection.
The conceptual API is:

```text
POST /extractions
  → 202 Accepted
  → { job_id, status: "pending", status_url, expires_at }

GET /extractions/{job_id}
  → pending | processing | succeeded | failed | rejected | expired
  → includes result only when succeeded
```

The Gateway authenticates every status lookup and verifies that the caller owns or is authorized
to inspect the job. An optional bounded wait parameter may reduce polling latency, but the durable
job and result contract remains asynchronous. Token streaming across the dead drop is outside the
initial vision.

Clients may supply an idempotency key. The Gateway maps repeated submissions from the same security
principal and operation to the existing job while the idempotency record is retained. The
server-generated request ID remains the canonical bridge identifier.

## Message Envelopes

Request and response files use versioned JSON envelopes. The final schema belongs in a separate
implementation contract, but every request must carry enough information to make processing
bounded and independently verifiable:

```json
{
  "schema_version": "aglea.request.v1",
  "request_id": "server-generated-uuid",
  "created_at": "RFC-3339 timestamp",
  "deadline": "RFC-3339 timestamp",
  "principal": { "subject": "opaque-id", "tenant": "opaque-id" },
  "authorization_scope": { "dataset_ids": ["approved-dataset-id"] },
  "operation": "extract",
  "payload": { "query": "bounded extraction instruction" },
  "integrity": { "algorithm": "deployment-selected", "value": "..." }
}
```

A response binds its result to the original request and represents exactly one terminal outcome:

```json
{
  "schema_version": "aglea.response.v1",
  "request_id": "server-generated-uuid",
  "completed_at": "RFC-3339 timestamp",
  "status": "succeeded",
  "result": {},
  "error": null,
  "integrity": { "algorithm": "deployment-selected", "value": "..." }
}
```

Failed, rejected, and expired responses contain a stable safe error code and omit sensitive
internal details. The Gateway signs requests and the Engine verifies them; the Engine protects
responses and the Gateway verifies them. Asymmetric signatures avoid sharing signing authority
between zones. A keyed MAC can be used only when its shared-secret trust implications are accepted
and documented.

Envelope encryption with an Engine-held decryption key is an optional additional control when
bridge readers must not see request content. It does not protect against a host administrator who
can inspect the running Engine or its memory.

## Atomic File-Drop Protocol

### Commit

Producers never write directly to a visible `.json` path:

1. Create a uniquely named `.tmp` file in the destination filesystem.
2. Write one bounded envelope and flush it.
3. `fsync` the file where the durability requirement warrants it, then close it.
4. Atomically replace or rename it to `<request-id>.json` in the committed directory.
5. `fsync` the parent directory where survival across sudden power loss is required.

Temporary files are ignored by consumers and removed by a TTL-based sweeper. The same protocol is
used for requests and responses. Atomicity requires source and destination to be on the same
filesystem; deployment validation must reject layouts that break that assumption.

### Claim

An Engine worker claims a request by atomically renaming:

```text
/bridge/requests/<request-id>.json
  → /bridge/processing/<request-id>.json
```

Only the worker that completes the rename owns the request. The source is not deleted before a
durable terminal response exists. A companion lease record or claimed-file metadata records the
worker identity and claim time.

### Complete

After inference, the Engine atomically commits a signed terminal response under
`/bridge/responses/`. The Gateway verifies it, updates its durable job registry, and makes the
result available to the authorized caller. Cleanup of the response and processing artifact occurs
only after the Gateway has durably recorded the terminal state, or after the configured retention
window.

Filesystem notifications such as inotify improve latency but are not the correctness mechanism.
Both zones periodically rescan their committed directories so missed events and process restarts do
not strand work.

## Lifecycle and Delivery Semantics

```text
authorized HTTP request
  → pending request file
  → atomically claimed processing file
  → local context selection and inference
  → terminal response file
  → verified Gateway job result
  → caller retrieval and bounded cleanup
```

The bridge provides at-least-once processing, not exactly-once execution. If a worker fails after
inference but before committing its response, recovery may run the request again. Therefore:

- request IDs are stable across retries;
- operations and response commits are idempotent;
- an existing valid terminal response wins over duplicate work;
- stale claims are retried only after their leases expire;
- attempt counts and deadlines bound poison-message loops; and
- conflicting responses for one request are quarantined and surfaced as an integrity failure.

On restart, the Engine first reconciles committed responses, active leases, stale processing files,
and pending requests. Malformed, oversized, unsupported, expired, or unauthenticated requests are
rejected or quarantined without reaching the model.

## Authorization and Sensitive Context

Authentication at the Gateway is necessary but not sufficient. Authorization scope must travel in
the protected request envelope and be enforced again when Zone C selects local context. The Engine
uses opaque, allowlisted resource identifiers resolved through a local policy map. It must never
interpret prompt text as permission to open a path or expand the authorized dataset set.

The LLM is not a policy enforcement point. Retrieved content may influence an extraction result,
but it cannot widen the caller's scope, alter bridge control fields, invoke executables, or request
network access.

## Failure, Capacity, and Retention Model

The Gateway rejects new work with `429` or `503` before filling the bridge when queue depth, file
count, or disk watermarks exceed configured bounds. Each deployment defines maximum envelope size,
maximum result size, queue capacity, inference attempts, job deadline, and retention periods.

Expected terminal conditions include:

| Condition | Outcome |
| --- | --- |
| Invalid authentication or authorization | Rejected before file creation |
| Invalid schema, signature, scope, or size | Quarantined or rejected without inference |
| Deadline reached before claim | Expired |
| Model or context-loading failure | Bounded retry, then failed |
| Gateway timeout or restart | Job remains durable and can be queried later |
| Engine restart during processing | Lease-based recovery may retry the request |
| Disk or queue watermark reached | Admission closes until capacity recovers |
| Duplicate request or response | Idempotent convergence or quarantine on conflict |

Unlinking a file is not secure erasure on journaling, copy-on-write, or backed-up storage. Sensitive
retention requirements should rely on encrypted storage with controlled key destruction, bounded
retention, and explicit backup policy rather than promises of immediate physical deletion.

## Observability and Audit

Operational records contain correlation IDs, authenticated principal identifiers where policy
allows, state transitions, attempt counts, timings, byte counts, model/artifact identities, and
stable error codes. Prompts, local context, credentials, signatures, and extracted results are not
written to general application logs.

Useful measures include queue depth, oldest pending age, claim-to-completion latency, end-to-end job
latency, success/rejection/failure counts, retry count, stale-lease recovery, disk watermarks, and
quarantine growth. Clock-dependent deadlines require controlled clock synchronization or a clearly
documented tolerance between zones; local durations use monotonic clocks.

## Security Boundary and Limitations

AGLEA removes direct network reachability between the Gateway and the inference boundary. It does
not, by itself, defend against:

- a compromised host or root administrator that can inspect both zones;
- malicious or vulnerable kernel, container runtime, or filesystem implementations;
- disclosure through unencrypted bridge backups or snapshots;
- model-level prompt injection or inaccurate extraction results; or
- denial of service through exhausted CPU, GPU, memory, inode, or disk capacity.

These risks require host hardening, verified artifacts, key management, storage encryption,
resource quotas, model evaluation, and operational monitoring in addition to the dead-drop design.
The term "air-gapped" in this document refers specifically to Zone C's lack of routable networking,
not to physical separation of the entire host.

## Initial Acceptance Principles

An AGLEA implementation should not be considered ready until it demonstrates that:

- Zone C completes representative extraction with all network interfaces disabled;
- partial `.tmp` files and missed watcher events never enter inference;
- forged, stale, malformed, oversized, and unauthorized envelopes fail closed;
- concurrent workers cannot successfully claim the same committed request;
- Gateway and Engine restarts recover pending and stale work without losing terminal results;
- duplicates converge without exposing conflicting results;
- queue and disk exhaustion trigger bounded backpressure rather than corruption;
- logs and metrics contain no request body, sensitive context, or extracted result; and
- a threat-model review verifies mounts, identities, keys, retention, and host assumptions.

## Deliberate Non-Goals for the First Iteration

- Token-by-token streaming across the bridge
- Exactly-once inference guarantees
- Multi-host or cross-filesystem queues
- General-purpose agent tool execution in Zone C
- Arbitrary user-selected filesystem access
- Replacement of the current v0.5 deployment topology

If later requirements need high throughput, multi-node scheduling, streaming, or general agent
execution, those features must preserve the authorization and isolation properties above or use a
separately reviewed architecture.
