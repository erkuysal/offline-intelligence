# Technical Vision v1 — Phase 8 Native Acceleration

Status: Completed — bounded contiguous path and air-gapped packaging accepted

## Intent

Introduce a small C component where measurement shows a useful native-code boundary, while keeping
correctness, portability, memory safety testing, and a Python fallback explicit.

## Initial Candidate

A cosine-similarity library provides a deliberately narrow learning and benchmarking surface:

```text
Python retrieval/evaluation code
   │ validated contiguous buffers
   ▼
standard-library ctypes boundary
   │
   ▼
portable C implementation
   ├── scalar baseline
   └── optional measured SIMD path
```

The production database already performs indexed vector retrieval. A native similarity function
must therefore demonstrate a real use case—such as local evaluation, reranking support, or batch
processing—rather than duplicating pgvector without benefit.

## Proposed Native and Binding Functions

| Function | Used for | Contract |
| --- | --- | --- |
| `oih_dot_f32()` | Shared dot-product primitive | Reads equal-length immutable float arrays and returns one scalar |
| `oih_l2_norm_f32()` | Computes vector magnitude | Returns `sqrt(sum(x_i²))` with documented zero/NaN behavior |
| `oih_cosine_similarity_f32()` | Computes one similarity score | Validates length and reports zero-vector/error status |
| `oih_cosine_batch_f32()` | Scores one query against contiguous document rows | Amortizes Python/native boundary overhead |
| Python `cosine_similarity()` | Validates arrays and invokes the native ABI | Owns dtype, contiguity, lifetime, and exception conversion |
| Python `cosine_similarity_fallback()` | Portable reference | Provides a correctness oracle and no-extension operation |
| `native_capabilities()` | Reports ABI/build/SIMD information | Makes runtime selection and benchmarks diagnosable |

The implemented scalar function names and status-code ABI are versioned as ABI `1`.

WP8.0 selected batch cosine for offline evaluation and experimental reranking; production dense
retrieval remains in PostgreSQL/pgvector. WP8.1 implemented scalar ABI version `1` with explicit
status codes and no allocation. WP8.2 added a standard-library `ctypes` binding that constructs
owned contiguous float32 buffers, exposes ABI/compiler capabilities, and automatically retains the
Python scalar oracle when the shared library is unavailable. Correctness/fuzz and
boundary-inclusive performance gates are complete. The kernel measured 12.5–40.3x faster than the
Python oracle, but nested-list conversion made the full boundary 0.45–0.69x as fast. List-based
activation is rejected; WP8.4 may test one already-contiguous offline path.
WP8.4 accepted that bounded path: top-20 ranking over 4,096 prepared 768-dimensional rows measured
`55.00x` faster with identical identities. The result applies only when conversion is absent;
production pgvector retrieval and list-shaped application paths remain unchanged. WP8.5 packages
the ABI-1 library through a digest-pinned multi-stage image, inventories its source/compiler/binary
identity, and proves a clean 23-file offline bundle with native and fallback operation under denied
outbound networking.

## Numerical Calculation

```text
dot = sum from i=0 to n-1 of a_i × b_i
norm_a = sqrt(sum a_i²)
norm_b = sqrt(sum b_i²)
cosine = dot / (norm_a × norm_b)
```

Zero-length and zero-norm vectors have no defined cosine similarity. The C API should return an
explicit error status translated into a Python exception rather than silently divide by zero.

Correctness comparison uses absolute and relative tolerance:

```text
absolute_error = abs(native - reference)
relative_error = absolute_error / max(abs(reference), epsilon)
pass = absolute_error <= atol + rtol × abs(reference)
```

Tolerance must be justified for float32. SIMD reassociation can alter low-order bits, so exact bit
equality is not the appropriate general contract.

## Performance Calculations

For `N` vectors of dimension `D`, scalar work is `O(N × D)`. A Python-to-C call has fixed overhead:

```text
total_native_time = binding_overhead + native_compute_time
speedup = python_reference_time / total_native_time
throughput = N / elapsed_seconds
```

Batching is therefore more likely to help than one native call per scalar score. Reports include
dimension, batch size, layout, dtype, CPU features, compiler flags, threads, and warm-up. A
microbenchmark win is insufficient without an end-to-end pipeline improvement.

## Memory and ABI Rules

- Inputs are borrowed immutable buffers; C never retains Python pointers after the call.
- Dimensions and byte-size multiplication are overflow-checked.
- The ABI uses explicit status/value contracts and avoids compiler-dependent exposed structs.
- Contiguous row-major float32 is the initial batch format; conversion cost is measured.
- SIMD dispatch checks runtime CPU support and retains a scalar path.
- Releasing the Python GIL for long batches requires immutable input guarantees.

## Engineering Requirements

- Defined input dimensions, dtype, alignment, ownership, and error behavior
- Numerically tested equivalence with a trusted implementation
- Zero-length, invalid-size, NaN, and extreme-value coverage
- Cross-platform CMake build with explicit compiler flags
- Address/undefined-behavior sanitizer, Valgrind where applicable, and fuzz coverage
- Scalar portable fallback before SIMD specialization
- Benchmarks that include Python/native boundary overhead
- Packaging that remains compatible with the Phase 7 offline bundle

## Promotion Rules

- Profile the current system and identify a measured bottleneck first.
- Do not move authorization, source identity, or other policy logic into the native layer.
- Retain a tested Python implementation for portability and diagnosis.
- Reject the native path if end-to-end improvement is immaterial or maintenance cost is excessive.
- Record CPU features and build metadata with benchmark results.

## Expected Deliverables

- Phase 8 profiling report and ADR selecting the native boundary
- C library, Python binding, portable fallback, and build integration
- Correctness, sanitizer, fuzz, and benchmark suites
- Offline packaging and compatibility metadata
- Acceptance or rejection record based on end-to-end measurements

## Dependency

This phase follows the production optimization and delivery work so native code is evaluated against
real hardware profiles and included in the same reproducible, air-gapped artifact lifecycle.
