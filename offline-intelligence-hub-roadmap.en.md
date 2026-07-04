# Offline Intelligence Hub — Development and Learning Roadmap

## Project Summary

**Offline Intelligence Hub** is an enterprise AI platform that can run in air-gapped and on-premise environments, analyzes internal documents, uses RAG, runs open-source LLMs, and can be customized with LoRA when needed.

Users can upload PDF, DOCX, TXT, or Markdown documents to the system. The system:

- Parses and indexes documents.
- Answers questions only from authorized documents.
- Provides sources in answers.
- Can use a fully local LLM.
- Can be installed without an internet connection.
- Can measure model and retrieval performance.
- Can be customized for specific domains with LoRA adapters.
- Can run on limited hardware with quantized models.
- Provides a REST API, user management, RBAC, audit logs, and monitoring.

This project aims to develop the main skills listed in the target job posting within a single product: Python, PyTorch, FastAPI, RAG, LoRA, PEFT, quantization, Docker, PostgreSQL, C, on-premise systems, and air-gapped systems.

---

## Final Architecture

```text
                         ┌─────────────────────┐
                         │ Vue 3 Admin Client  │
                         └──────────┬──────────┘
                                    │
                              HTTPS / SSE
                                    │
                         ┌──────────▼──────────┐
                         │    Nginx / Caddy    │
                         └──────────┬──────────┘
                                    │
                    ┌───────────────▼────────────────┐
                    │            FastAPI             │
                    │ Auth · Documents · Chat · RAG  │
                    └───────┬─────────┬─────────┬────┘
                            │         │         │
                   ┌────────▼───┐ ┌───▼────┐ ┌──▼──────────┐
                   │ PostgreSQL │ │ Redis  │ │ Worker      │
                   │ + pgvector │ │ Cache  │ │ Ingestion   │
                   └────────────┘ └────────┘ └─────┬───────┘
                                                   │
                                     ┌─────────────▼───────────┐
                                     │ Local Inference Server  │
                                     │ Transformers/llama.cpp  │
                                     └─────────────┬───────────┘
                                                   │
                          ┌────────────────────────▼───────────┐
                          │ Base Model · LoRA · Quantized GGUF │
                          └────────────────────────────────────┘
```

---

# Development Phases

## Phase 1 — Working Product Skeleton

The first goal is not an advanced AI system, but a basic end-to-end working product.

### Features

- FastAPI REST API
- PostgreSQL
- SQLAlchemy
- Alembic migrations
- User registration and login
- JWT authentication
- Role-Based Access Control
- Document upload
- Document metadata records
- Docker Compose
- Health check
- Structured logging
- Unit and integration tests

### Skills to Learn

- Advanced Python
- FastAPI
- SQL
- Relational database design
- REST API development
- Docker
- Git
- Backend architecture
- Technical documentation

### Initial Endpoints

```text
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh

POST   /api/v1/documents
GET    /api/v1/documents
GET    /api/v1/documents/{id}
DELETE /api/v1/documents/{id}

GET    /health
GET    /metrics
```

At this stage, there is no LLM or RAG yet.

---

## Phase 2 — Local LLM Integration

In the second iteration, an open-source instruction model is run locally.

### First Target

```text
POST /api/v1/chat/completions
```

OpenAI API-like contract:

```json
{
  "model": "local-model",
  "messages": [
    {
      "role": "user",
      "content": "Summarize this document."
    }
  ],
  "temperature": 0.2,
  "stream": true
}
```

### Components to Implement

- Hugging Face Transformers adapter
- llama.cpp adapter
- Model configuration
- Model warm-up
- Streaming response
- Request cancellation
- Timeout
- Concurrency limit
- Token usage tracking
- CPU/GPU selection
- Prometheus metrics

---

## Phase 3 — Document Ingestion and RAG

At this stage, the platform becomes an enterprise knowledge system.

### Document Pipeline

```text
Upload
  ↓
Virus/type validation
  ↓
Text extraction
  ↓
Cleaning
  ↓
Chunking
  ↓
Embedding
  ↓
Vector indexing
  ↓
Retrieval
  ↓
Prompt construction
  ↓
Local LLM
  ↓
Answer + citations
```

### First Supported Formats

- PDF
- TXT
- Markdown
- DOCX

### RAG Features

- Recursive chunking
- Configurable chunk size
- Chunk overlap
- Embedding generation
- Vector similarity search
- Metadata filtering
- Source citations
- Conversation history
- Incremental reindexing
- Duplicate document detection
- Document-level access control

### Data Model

```text
users
roles
documents
document_versions
document_permissions
chunks
embeddings
conversations
messages
retrieval_runs
audit_logs
```

The first version uses `pgvector`. PostgreSQL manages both relational data and the embedding layer.

---

## Phase 4 — Hybrid Retrieval and Evaluation

After basic vector search, the RAG system is measured to verify whether it actually works.

### Retrieval Improvements

- Dense vector retrieval
- PostgreSQL full-text search
- Hybrid retrieval
- Metadata filtering
- Reranking
- Query rewriting
- Multi-query retrieval
- Context deduplication

### Example Evaluation Dataset

```json
{
  "question": "What is the system backup procedure?",
  "expected_answer": "Incremental backups are taken every night, and a full backup is taken on Sundays.",
  "expected_document_ids": ["backup-policy-v2"],
  "expected_chunk_ids": ["chunk-148", "chunk-149"]
}
```

### Metrics to Measure

- Recall@k
- Precision@k
- Mean Reciprocal Rank
- Citation accuracy
- Context relevance
- Answer faithfulness
- Hallucination rate
- Time to first token
- End-to-end latency
- Tokens per second

---

## Phase 5 — LoRA and PEFT

After the RAG system is working, the open-source model is customized for specific tasks.

### Fine-Tuning Goals

- Turkish technical answer format
- Refusing questions outside the provided sources
- Producing specific JSON outputs
- Creating technical incident reports
- Using specific terminology consistently
- Mandatory source format in answers

### Training Pipeline

```text
Raw examples
    ↓
Data validation
    ↓
Chat-template conversion
    ↓
Train / validation split
    ↓
Base-model evaluation
    ↓
LoRA training
    ↓
Adapter evaluation
    ↓
Adapter export
    ↓
Inference deployment
```

### Versions to Compare

1. Base model
2. Base model + RAG
3. LoRA model
4. LoRA model + RAG

### Training Configuration

- `r`
- `lora_alpha`
- `lora_dropout`
- `target_modules`
- Learning rate
- Batch size
- Gradient accumulation
- Gradient checkpointing
- Mixed precision
- Maximum sequence length
- Epoch and early stopping
- Adapter merge

---

## Phase 6 — Quantization and Inference Optimization

At this stage, the platform is prepared for low-resource on-premise systems.

### Model Formats to Test

- BF16 or FP16
- INT8
- 4-bit
- GGUF Q8
- GGUF Q5
- GGUF Q4

### Benchmark Output

```text
Model:
Quantization:
Disk size:
Peak RAM:
Peak VRAM:
Startup duration:
Time to first token:
Tokens per second:
Retrieval latency:
Generation latency:
Evaluation score:
```

### Approaches

- **llama.cpp / GGUF:** practical local inference and CPU-heavy deployment
- **PyTorch / torchao:** deeper learning of quantization mechanisms

---

## Phase 7 — Air-Gapped Deployment

The platform is moved to a target server with no internet access.

### Environments

#### Build Environment

- Has internet access.
- Docker images are prepared.
- Python packages are downloaded.
- Model files are retrieved.
- Checksums and manifests are generated.

#### Air-Gapped Target

- Has no internet access.
- Uses only the prepared release bundle.
- External telemetry is disabled.
- Model and dependency files are local.

### Release Package

```text
offline-release/
├── images/
│   ├── api.tar
│   ├── worker.tar
│   ├── frontend.tar
│   └── inference.tar
├── wheels/
├── models/
├── migrations/
├── configs/
├── manifests/
├── checksums.sha256
├── install.sh
├── verify.sh
├── backup.sh
├── restore.sh
└── AIR_GAPPED_INSTALLATION.md
```

### Air-Gapped Features

- Internal-only Docker networks
- No outbound network
- Offline Python wheelhouse
- Offline container images
- Local model storage
- SHA-256 verification
- SBOM
- Non-root containers
- Read-only filesystem where possible
- Audit logging
- Backup/restore
- Model version registry
- Dependency version manifest

---

## Phase 8 — C Integration

Instead of a separate project for C, a native module is added to the existing system.

### Proposed Module

C-based cosine similarity function:

```c
float cosine_similarity(
    const float *a,
    const float *b,
    size_t length
);
```

Python integration:

```text
Python RAG Service
       │
       ▼
CFFI / ctypes
       │
       ▼
Native Similarity Library
```

### Topics to Learn

- Pointer
- Array and memory layout
- Struct
- Dynamic memory
- Shared library
- CMake
- Compiler flags
- GDB
- Valgrind
- Python/C interoperability
- Simple SIMD optimization
- Benchmarking

Later, the latency difference between the Python and C implementations is measured.

---

# Repository Structure

```text
offline-intelligence-hub/
├── apps/
│   ├── api/
│   │   ├── app/
│   │   ├── migrations/
│   │   └── tests/
│   ├── worker/
│   ├── web/
│   └── inference/
│
├── packages/
│   ├── rag/
│   ├── evaluation/
│   ├── model_gateway/
│   └── common/
│
├── training/
│   ├── datasets/
│   ├── scripts/
│   ├── configs/
│   ├── lora/
│   └── quantization/
│
├── native/
│   └── vector_similarity/
│
├── infrastructure/
│   ├── docker/
│   ├── nginx/
│   ├── prometheus/
│   └── offline/
│
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── security/
│   └── deployment/
│
├── benchmarks/
├── scripts/
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

This full structure is not populated at the beginning. Only the required directories are created in the first sprint.

---

# Sprint 1 — Product Skeleton

## Goal

A Docker-based FastAPI application where the user can register, log in, and upload a document.

## Sprint Backlog

### Backend

- FastAPI application skeleton
- Settings management
- PostgreSQL connection
- SQLAlchemy models
- Alembic migration
- User model
- Role model
- Document model
- JWT login
- Refresh token
- Document upload
- File type and size validation
- Health endpoint
- Structured logging

### Infrastructure

- API Dockerfile
- PostgreSQL container
- Redis container
- Docker Compose
- Persistent volumes
- `.env.example`
- Makefile or task runner

### Testing

- Authentication unit test
- Document upload integration test
- Database fixture
- Health endpoint test

### Documentation

- README
- Local setup
- API usage
- Architecture Decision Record

## Sprint Acceptance Criteria

```text
[ ] The system starts with docker compose up
[ ] PostgreSQL migration runs automatically or is documented
[ ] A user can be created
[ ] A JWT can be obtained
[ ] Protected endpoint access works
[ ] PDF/TXT files can be uploaded
[ ] Metadata is saved to PostgreSQL
[ ] The file is written to local storage
[ ] Tests run inside the container
[ ] The /health endpoint returns 200
```

---

# Initial Technical Decisions

## Python Version

A current Python 3.x version with strong library compatibility is pinned. All versions are pinned in `pyproject.toml` and in the container image.

## Dependency Management

For the beginning:

- `uv`
- `pyproject.toml`
- Lock file

In the air-gapped phase, packages are converted into an offline wheelhouse.

## Backend Structure

```text
apps/api/app/
├── main.py
├── config.py
├── database.py
├── dependencies.py
├── api/
│   └── v1/
├── models/
├── schemas/
├── repositories/
├── services/
├── security/
└── observability/
```

## Code Layers

```text
Router
  ↓
Service
  ↓
Repository
  ↓
SQLAlchemy
  ↓
PostgreSQL
```

Business logic is not kept inside API routers.

## Initial Data Models

```text
User
- id
- email
- password_hash
- is_active
- created_at

Role
- id
- name

UserRole
- user_id
- role_id

Document
- id
- owner_id
- filename
- content_type
- storage_path
- sha256
- status
- created_at
```

---

# Incremental Product Versions

| Version | Product Output | Main Skill Learned |
|---|---|---|
| v0.1 | Auth and document upload | FastAPI, SQL, Docker |
| v0.2 | Local LLM chat | Open-source LLM inference |
| v0.3 | Vector RAG | Embeddings, pgvector |
| v0.4 | Hybrid RAG | Retrieval, reranking |
| v0.5 | Evaluation suite | AI evaluation |
| v0.6 | LoRA adapter | PyTorch, PEFT, fine-tuning |
| v0.7 | Quantized inference | torchao, GGUF, optimization |
| v0.8 | Air-gapped release | On-premise deployment |
| v0.9 | Native C module | C/Python interoperability |
| v1.0 | Production portfolio release | Documentation and productization |

---

# Starting Point

First, `v0.1` is developed.

## First Commit

```text
feat: bootstrap FastAPI service with PostgreSQL and Docker
```

## First Commit Scope

```text
offline-intelligence-hub/
├── apps/api/app/main.py
├── apps/api/app/config.py
├── apps/api/tests/test_health.py
├── apps/api/Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .env.example
└── README.md
```

## First Endpoint

```python
@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}
```

Then development proceeds in this order:

1. PostgreSQL connection
2. Alembic migrations
3. User model
4. Authentication
5. Document upload
6. Local LLM integration
7. RAG pipeline
8. Evaluation
9. LoRA / PEFT
10. Quantization
11. Air-gapped deployment
12. Native C module

With this approach, every topic learned becomes part of a working product; no code is written only as a disposable exercise.
