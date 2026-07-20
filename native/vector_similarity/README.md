# OIH Vector Similarity Native Library

This directory contains the portable C11 scalar baseline for Phase 8. It is an optional batch
primitive for offline evaluation and experimental reranking; PostgreSQL/pgvector remains the
production dense-retrieval implementation.

## ABI

`include/oih_vector_similarity.h` exposes ABI version `1` and four float32-input functions:

- `oih_dot_f32`
- `oih_l2_norm_f32`
- `oih_cosine_similarity_f32`
- `oih_cosine_batch_f32`

Inputs are borrowed, immutable, and never retained. The library performs no dynamic allocation.
Output is valid only when the returned status is `OIH_VECTOR_OK`; batch output may be partially
written if a later row fails, so callers must discard the entire result on any non-zero status.

Status codes distinguish null pointers, zero lengths, size multiplication overflow, zero norms, and
non-finite inputs/results. A zero vector has a valid L2 norm of zero but is rejected for cosine
similarity.

## Build and Test

```bash
cmake -S native/vector_similarity -B var/build/vector-similarity \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build var/build/vector-similarity --parallel
ctest --test-dir var/build/vector-similarity --output-on-failure
```

Sanitizer build:

```bash
cmake -S native/vector_similarity -B var/build/vector-similarity-sanitize \
  -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON -DOIH_ENABLE_SANITIZERS=ON
cmake --build var/build/vector-similarity-sanitize --parallel
ctest --test-dir var/build/vector-similarity-sanitize --output-on-failure
```

Leak detection is disabled only for the CTest process because LeakSanitizer cannot run under the
current ptrace wrapper. AddressSanitizer and UndefinedBehaviorSanitizer remain enabled. The library
does not allocate or own heap memory.

## Python Binding

`apps/api/app/native/vector_similarity.py` uses the standard-library `ctypes` module. Supply an
explicit library path or set `OIH_VECTOR_LIBRARY`; packaged operation will search beside the Python
module. Inputs are converted to owned contiguous float32 arrays, and the arrays remain alive for the
entire native call. If loading or ABI validation fails, the public API uses the Python scalar oracle
and reports the reason through `native_capabilities()`.
