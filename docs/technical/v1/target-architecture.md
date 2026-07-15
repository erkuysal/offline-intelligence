# Technical Vision v1 — Target Architecture

## Vision

Offline Intelligence Hub is a local-first document intelligence platform whose answers are grounded
in authorized content, whose model behavior is measurable, and whose complete runtime can eventually
be installed and operated without internet access.

```text
Browser
   │ HTTPS / SSE
   ▼
Reverse proxy
   │
   ▼
FastAPI ───────────────► PostgreSQL + pgvector
   │                         documents, permissions,
   │                         chunks, conversations,
   │                         retrieval diagnostics
   ├───────────────────► Redis / bounded background work
   │
   ├── retrieval pipeline
   │      dense · lexical · fusion · optional refinement
   │
   └── model gateway ──► local inference runtime
                              base model
                              optional LoRA adapter
                              selected quantization
```

## Enduring Boundaries

- Authorization is enforced before retrieved content can influence ranking, prompts, or answers.
- RAG owns changeable organizational knowledge; model adaptation owns behavior and output style.
- External model runtimes sit behind application-owned interfaces and bounded failure contracts.
- Every optional retrieval or model enhancement has a safe baseline fallback.
- Evaluation uses versioned datasets, pinned model revisions, machine-readable reports, and explicit
  promotion thresholds.
- Operational defaults are local and privacy-preserving; sensitive query and passage text is not
  persisted merely for observability.
- Offline delivery must be verifiable from manifests and checksums, not dependent on hidden caches.

## Component Responsibilities

| Component | Used for | Why it owns that responsibility |
| --- | --- | --- |
| Vue client | Authentication, document workflows, grounded chat, source inspection | Keeps browser state and interaction concerns outside the API |
| Reverse proxy | Single-origin routing, static assets, API/SSE forwarding | Gives the browser one stable origin and a deployment policy boundary |
| FastAPI | Validation, authentication, authorization, orchestration, public contracts | Business rules remain testable and independent of model-server internals |
| PostgreSQL | Users, documents, permissions, chunks, vectors, conversations, diagnostics | Transactions keep metadata, authorization, and retrieval state consistent |
| Redis | Bounded ingestion queue state | Supports asynchronous work without making Redis the durable source of truth |
| Retrieval pipeline | Candidate production, fusion, refinement, context selection | Separates search quality decisions from generation behavior |
| Model gateway | Health, limits, streaming, error translation | Prevents the application from depending on one inference implementation |
| Local model runtime | Tokenization and tensor execution | Keeps expensive model execution replaceable and independently configurable |
| Evaluation runners | Dataset preparation, scoring, thresholds, reports | Makes promotion decisions reproducible rather than subjective |

## Main Request Paths

### Document ingestion

```text
HTTP bytes → size/hash validation → durable file → document row
           → extraction → chunks → embeddings → ready state
```

The document is retrievable only after successful extraction, chunk persistence, and embedding.
Failures produce an explicit failed state; they do not expose a partially indexed corpus.

### Grounded chat

```text
question + user identity + optional document IDs
  → authorized retrieval
  → bounded/deduplicated context
  → grounded system instruction
  → streamed local generation
  → persisted answer, usage, and selected citations
```

Authorization is carried as input into retrieval. It is not inferred after candidates are returned,
and it is never delegated to the language model.

### Artifact promotion

```text
candidate artifact + pinned evaluator + accepted dataset
  → quality/safety/performance report
  → all thresholds pass?
       yes: version, checksum, deploy, retain rollback
       no:  preserve report, do not promote
```

## Common Calculations

- Durations use a monotonic clock: `duration_ms = (end - start) × 1000`.
- Throughput uses generated completion tokens only:
  `tokens_per_second = completion_tokens / generation_seconds`.
- A P95 value is selected from sorted observations near index `floor(N × 0.95)`; it represents tail
  behavior and is reported alongside the mean.
- Version compatibility is an equality contract across configured and reported model revisions;
  explicit experimental overrides must not silently become production defaults.

## Evolution by Phase

```text
Product foundation
    ↓
Local model contract
    ↓
Permission-aware RAG
    ↓
Measured retrieval and generation
    ↓
Behavior adaptation with LoRA
    ↓
Quantized hardware profiles
    ↓
Air-gapped release lifecycle
    ↓
Optional native acceleration
```

Later phases refine earlier layers rather than bypassing them. A LoRA adapter cannot weaken RAG
authorization. Quantization cannot be promoted solely for speed if it violates quality gates. A C
module cannot become correctness-critical without a tested portable fallback.

## Evidence Flow

Each material runtime artifact should be traceable through:

```text
source revision
  + dataset revision
  + model / adapter revision
  + build configuration
  + evaluation report
  + artifact checksum
  = reproducible release decision
```

This chain becomes progressively more important in Phases 5–7, where generated model artifacts and
offline bundles join source code as release inputs.
