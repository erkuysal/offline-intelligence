# Offline Intelligence Hub — Geliştirme ve Öğrenme Yol Haritası

## Proje Özeti

**Offline Intelligence Hub**, air-gapped ve on-premise ortamlarda çalışabilen, kurum içi dokümanları analiz eden, RAG kullanan, açık kaynaklı LLM'leri çalıştıran ve gerektiğinde LoRA ile özelleştiren kurumsal yapay zekâ platformudur.

Kullanıcı sisteme PDF, DOCX, TXT veya Markdown dokümanları yükleyebilir. Sistem:

- Dokümanları ayrıştırır ve indeksler.
- Sorulara yalnızca yetkili dokümanlardan cevap verir.
- Cevaplarda kaynak gösterir.
- Tamamen yerel bir LLM kullanabilir.
- İnternet bağlantısı olmadan kurulabilir.
- Model ve retrieval performansını ölçebilir.
- LoRA adapter'larıyla alan odaklı özelleştirilebilir.
- Quantized modellerle sınırlı donanımda çalışabilir.
- REST API, kullanıcı yönetimi, RBAC, audit log ve monitoring sunar.

Bu proje; Python, PyTorch, FastAPI, RAG, LoRA, PEFT, quantization, Docker, PostgreSQL, C, on-premise ve air-gapped sistemler gibi hedef ilandaki ana yetkinlikleri tek ürün içinde geliştirmeyi amaçlar.

---

## Nihai Mimari

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

# Geliştirme Fazları

## Faz 1 — Çalışan Ürün İskeleti

İlk hedef, yapay zekâ açısından gelişmiş bir sistem değil; uçtan uca çalışan temel üründür.

> **Şu anki konum:** Faz 2 başladı. Faz 1 tamamlandı; şimdi OpenAI uyumlu `/api/v1/chat/completions` sözleşmesi, fake LLM backend, `/health/llm` endpoint'i ve daha sonra `llama-server` gibi yerel OpenAI-compatible backend bağlantısı ekleniyor.

### Özellikler

- FastAPI REST API
- PostgreSQL
- SQLAlchemy
- Alembic migrations
- Kullanıcı kaydı ve girişi
- JWT authentication
- Role-Based Access Control
- Doküman yükleme
- Doküman metadata kayıtları
- Docker Compose
- Health check
- Structured logging
- Unit ve integration testleri

### Öğrenilecek Yetkinlikler

- İleri Python
- FastAPI
- SQL
- Relational database design
- REST API development
- Docker
- Git
- Backend architecture
- Teknik dokümantasyon

### İlk Endpoint'ler

```text
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh

POST   /api/v1/documents
GET    /api/v1/documents
GET    /api/v1/documents/{id}
DELETE /api/v1/documents/{id}

GET    /api/v1/users/me
GET    /api/v1/admin/health

GET    /health
GET    /health/db
GET    /health/redis
GET    /health/llm
GET    /metrics
```

Bu aşamada henüz LLM veya RAG bulunmaz.

---

## Faz 2 — Yerel LLM Entegrasyonu

İkinci iterasyonda açık kaynaklı bir instruction model yerel olarak çalıştırılır.

### İlk Hedef

```text
POST /api/v1/chat/completions
```

OpenAI API benzeri sözleşme:

- `messages`
- `model`
- `temperature`
- `max_tokens`
- `stream: false`

İlk implementasyon fake backend ile test edilebilir durumda tutulur. Gerçek yerel model için OpenAI-compatible bir servis (`llama-server` gibi) `LLM_BASE_URL` üzerinden bağlanır. İlk doğrulanan model `ggml-org/gemma-3-1b-it-GGUF:Q4_K_M` olmuştur.

```json
{
  "model": "local-model",
  "messages": [
    {
      "role": "user",
      "content": "Bu dokümanı özetle."
    }
  ],
  "temperature": 0.2,
  "max_tokens": 512,
  "stream": false
}
```

### Uygulanacak Bileşenler

- OpenAI-compatible local backend adapter
- Fake backend
- Model configuration
- LLM probe command (`./app.py llm-probe`)
- llama.cpp server integration
- Model warm-up
- Streaming response
- Request cancellation
- Timeout
- Concurrency limit
- Token usage tracking
- CPU/GPU seçimi
- Prometheus metrics

---

## Faz 3 — Doküman Ingestion ve RAG

Bu aşamada platform kurumsal bilgi sistemine dönüşür.

### Doküman Pipeline'ı

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

### İlk Desteklenecek Formatlar

- PDF
- TXT
- Markdown
- DOCX

### RAG Özellikleri

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

### Veri Modeli

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

İlk sürümde `pgvector` kullanılır. PostgreSQL hem ilişkisel veriyi hem de embedding katmanını yönetir.

---

## Faz 4 — Hybrid Retrieval ve Evaluation

Basit vector search sonrasında RAG sisteminin gerçekten çalışıp çalışmadığı ölçülür.

### Retrieval Geliştirmeleri

- Dense vector retrieval
- PostgreSQL full-text search
- Hybrid retrieval
- Metadata filtering
- Reranking
- Query rewriting
- Multi-query retrieval
- Context deduplication

### Değerlendirme Veri Seti Örneği

```json
{
  "question": "Sistemin yedekleme prosedürü nedir?",
  "expected_answer": "Her gece artımlı, pazar günü tam yedek alınır.",
  "expected_document_ids": ["backup-policy-v2"],
  "expected_chunk_ids": ["chunk-148", "chunk-149"]
}
```

### Ölçülecek Metrikler

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

## Faz 5 — LoRA ve PEFT

RAG sistemi çalıştıktan sonra açık kaynaklı model belirli görevler için özelleştirilir.

### Fine-Tuning Amaçları

- Türkçe teknik cevap formatı
- Kaynak dışı soruları reddetme
- Belirli JSON çıktıları üretme
- Teknik olay raporu oluşturma
- Belirli terminolojiyi tutarlı kullanma
- Cevaplarda zorunlu kaynak formatı

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

### Karşılaştırılacak Sürümler

1. Base model
2. Base model + RAG
3. LoRA model
4. LoRA model + RAG

### Eğitim Konfigürasyonu

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
- Epoch ve early stopping
- Adapter merge

---

## Faz 6 — Quantization ve Inference Optimizasyonu

Bu aşamada platform düşük kaynaklı on-premise sistemlere hazırlanır.

### Test Edilecek Model Formatları

- BF16 veya FP16
- INT8
- 4-bit
- GGUF Q8
- GGUF Q5
- GGUF Q4

### Benchmark Çıktısı

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

### Yaklaşımlar

- **llama.cpp / GGUF:** pratik yerel inference ve CPU ağırlıklı deployment
- **PyTorch / torchao:** quantization mekanizmalarını daha derin öğrenme

---

## Faz 7 — Air-Gapped Deployment

Platform internet erişimi olmayan hedef sunucuya taşınır.

### Ortamlar

#### Build Environment

- İnternet erişimi var.
- Docker image'ları hazırlanır.
- Python paketleri indirilir.
- Model dosyaları alınır.
- Checksum ve manifest üretilir.

#### Air-Gapped Target

- İnternet erişimi yoktur.
- Yalnızca hazırlanan release bundle kullanılır.
- Harici telemetry kapalıdır.
- Model ve dependency dosyaları lokaldir.

### Release Paketi

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

### Air-Gapped Özellikler

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

## Faz 8 — C Entegrasyonu

C için ayrı bir proje yerine mevcut sisteme native bir modül eklenir.

### Önerilen Modül

C tabanlı cosine similarity fonksiyonu:

```c
float cosine_similarity(
    const float *a,
    const float *b,
    size_t length
);
```

Python entegrasyonu:

```text
Python RAG Service
       │
       ▼
CFFI / ctypes
       │
       ▼
Native Similarity Library
```

### Öğrenilecek Konular

- Pointer
- Array ve memory layout
- Struct
- Dynamic memory
- Shared library
- CMake
- Compiler flags
- GDB
- Valgrind
- Python/C interoperability
- Basit SIMD optimizasyonu
- Benchmarking

Daha sonra Python ve C implementasyonlarının latency farkı ölçülür.

---

# Repository Yapısı

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

Başlangıçta bu yapının tamamı doldurulmaz. İlk sprintte yalnızca gerekli dizinler oluşturulur.

---

# Sprint 1 — Ürün İskeleti

## Hedef

Kullanıcının sisteme kaydolabildiği, oturum açabildiği ve bir doküman yükleyebildiği Docker tabanlı FastAPI uygulaması.

## Sprint Backlog

### Backend

- [x] FastAPI uygulama iskeleti
- [x] Settings yönetimi
- [x] PostgreSQL bağlantısı
- [x] SQLAlchemy modelleri
- [x] Alembic migration
- [x] User modeli
- [x] Role modeli
- [x] Document modeli
- [x] JWT login
- [x] Refresh token
- [x] Temel RBAC
- [x] Document upload
- [x] Document delete
- [x] File type ve size validation
- [x] Health endpoint
- [x] Structured logging
- [x] `/metrics` endpoint

### Infrastructure

- [x] API Dockerfile
- [x] PostgreSQL container
- [x] Redis container
- [x] Docker Compose
- [x] Persistent volumes
- [x] `.env.example`
- [x] Django benzeri task runner (`./app.py`)
- [x] Smoke test script

### Testing

- [x] Authentication unit test
- [x] Refresh token testleri
- [x] RBAC testleri
- [x] Document upload integration test
- [x] Document delete integration test
- [x] Database fixture
- [x] Health endpoint test
- [x] Redis health endpoint test
- [x] Smoke test
- [x] Container içinde test çalıştırma

### Documentation

- [x] README
- [x] Local setup
- [x] API usage
- [x] Architecture Decision Record

## Sprint Kabul Kriterleri

```text
[x] docker compose up ile PostgreSQL, Redis ve API başlıyor
[x] PostgreSQL migration API container başlangıcında otomatik çalışıyor
[x] Kullanıcı oluşturulabiliyor
[x] Access token ve refresh token alınabiliyor
[x] Korumalı endpoint erişimi çalışıyor
[x] Temel RBAC çalışıyor
[x] PDF/TXT yüklenebiliyor
[x] Metadata PostgreSQL'e kaydediliyor
[x] Dosya lokal storage'a yazılıyor
[x] Doküman metadata ve lokal dosya birlikte silinebiliyor
[x] Smoke test gerçek HTTP akışını doğruluyor
[x] Testler container içinde çalışıyor
[x] /health endpoint'i 200 dönüyor
[x] /health/db endpoint'i 200 dönüyor
[x] /health/redis endpoint'i 200 dönüyor
[x] /metrics endpoint'i 200 dönüyor
```

---

# İlk Teknik Kararlar

## Python Sürümü

Güncel ve kütüphane uyumluluğu yüksek bir Python 3.x sürümü sabitlenir. Tüm sürümler `pyproject.toml` ve container image içinde pinlenir.

## Dependency Yönetimi

Başlangıç için:

- `uv`
- `pyproject.toml`
- Lock file

Air-gapped aşamada paketler offline wheelhouse'a dönüştürülür.

## Backend Yapısı

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

## Kod Katmanları

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

Business logic API router içinde tutulmaz.

## İlk Veri Modelleri

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

# Ürünün Aşamalı Sürümleri

| Sürüm | Ürün Çıktısı | Öğrenilen Ana Yetkinlik |
|---|---|---|
| v0.1 | Auth ve document upload | FastAPI, SQL, Docker |
| v0.2 | Local LLM chat | Open-source LLM inference |
| v0.3 | Vector RAG | Embeddings, pgvector |
| v0.4 | Hybrid RAG | Retrieval, reranking |
| v0.5 | Evaluation suite | AI evaluation |
| v0.6 | LoRA adapter | PyTorch, PEFT, fine-tuning |
| v0.7 | Quantized inference | torchao, GGUF, optimization |
| v0.8 | Air-gapped release | On-premise deployment |
| v0.9 | Native C module | C/Python interoperability |
| v1.0 | Production portfolio release | Dokümantasyon ve ürünleştirme |

---

# Başlangıç Noktası

İlk olarak `v0.1` geliştirilir.

## İlk Commit

```text
feat: bootstrap FastAPI service with PostgreSQL and Docker
```

## İlk Commit Kapsamı

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

## İlk Endpoint

```python
@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}
```

Ardından şu sırayla ilerlenir:

1. PostgreSQL bağlantısı
2. Alembic migrations
3. Kullanıcı modeli
4. Authentication
5. Document upload
6. RBAC
7. Document delete
8. Structured logging ve metrics
9. Local LLM integration
10. RAG pipeline
11. Evaluation
12. LoRA / PEFT
13. Quantization
14. Air-gapped deployment
15. Native C module

Bu yaklaşımda öğrenilen her konu çalışan ürünün bir parçası olur; yalnızca alıştırma amacıyla yazılıp atılan kod oluşmaz.
