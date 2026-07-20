# Phase 8 Barebones Native Acceleration Plan

Status: Completed — bounded native path and offline packaging accepted

## Scope Decision

Phase 8 will add one small, optional C batch-cosine component with a Python fallback. PostgreSQL with
pgvector remains the production dense-retrieval owner. The native component initially serves
offline evaluation and experimental reranking only; it is promoted into a runtime path only if an
end-to-end benchmark shows material value without weakening correctness, portability, or the Phase
7 offline contract.

Broad C rewrites, custom database indexes, authorization logic, GPU kernels, and mandatory native
dependencies are outside the barebones scope.

## Work Package 8.0: Profile and Select the Boundary

- [x] Inventory current vector operations and identify the production owner
- [x] Define a versioned deterministic Python baseline contract
- [x] Measure scalar and batch workloads including call overhead
- [x] Record a machine-readable report and a bounded proceed/reject decision

The selected boundary is batch cosine similarity over contiguous float32 rows. Single-vector calls
are too small to justify native dispatch: 768 dimensions measured `0.032` ms P50. The useful
measurement surface is a batch of 256 rows at 768 dimensions, which measured `6.191` ms P50 and
approximately `41,270` vectors/s in scalar Python. The decision is `proceed_experimental_only`.

Implemented command:

```bash
./manage.py native-vector-profile \
  --contract config/native/vector-similarity-profile-v1.json \
  --output var/native/vector-similarity-python-baseline.json
```

## Work Package 8.1: Portable C ABI

- [x] Implement scalar dot product, norm, single cosine, and batch cosine
- [x] Use explicit status codes for null, zero-length, size overflow, and zero-norm inputs
- [x] Keep borrowed input memory immutable and retain no caller pointers
- [x] Build a shared library through CMake with warnings treated as errors

The ABI is version `1`, uses float32 inputs with double scalar accumulation, performs no dynamic
allocation, and treats batch output as invalid on any non-zero status. Release and debug sanitizer
builds passed CTest under GCC 15.2.0 with warnings-as-errors, AddressSanitizer, and
UndefinedBehaviorSanitizer. LeakSanitizer alone is disabled under the current ptrace wrapper; the
library owns no heap memory.

## Work Package 8.2: Python Binding and Fallback

- [x] Validate dtype, row-major contiguity, dimensions, and buffer lifetime before native calls
- [x] Translate native status codes into stable Python exceptions
- [x] Expose ABI/build/capability metadata
- [x] Automatically retain the tested Python implementation when the library is unavailable

The implemented `ctypes` binding adds no runtime package dependency. It owns contiguous float32
buffers for each call, keeps them alive across native execution, checks ABI version `1`, exposes the
library path and compiler/build string, maps status codes to stable exceptions, and falls back to
the Python oracle when the shared library is unavailable. Buffer conversion cost remains part of
the next boundary-inclusive benchmark.

## Work Package 8.3: Correctness and Memory Safety

- [x] Compare native and fallback outputs with justified float32 tolerances
- [x] Cover empty, mismatched, zero-norm, NaN, infinity, extreme, and overflow-shaped inputs
- [x] Run AddressSanitizer and UndefinedBehaviorSanitizer tests
- [x] Add deterministic fuzz/property coverage across dimensions and batch sizes

The seeded gate compared 1,640 values across 200 cases with zero tolerance failures. Maximum
absolute error was `2.943e-08` against `atol=1e-6` and `rtol=1e-5`. Release and ASan/UBSan CTest
builds passed. The scalar kernel was 12.5–40.3x faster, but list-to-float32 conversion dominated the
public boundary, making it only 0.45–0.69x as fast as fallback. Correctness is accepted; list-based
performance promotion is rejected.

## Work Package 8.4: Benchmark and Bounded Integration

- [x] Benchmark fallback, binding conversion, and native compute separately
- [x] Report P50/P95, throughput, input bytes, CPU/compiler flags, and break-even batch size
- [x] Integrate only one offline evaluation or experimental reranking path behind explicit selection
- [x] Reject production activation if the end-to-end gain is immaterial

The bounded integration ranks a prepared contiguous float32 evaluation matrix and does not replace
pgvector. For 4,096 rows at 768 dimensions with top-20 selection, fallback measured `144.197` ms
P50 and native measured `2.621` ms P50, a `55.00x` scoring-plus-ranking speedup. Top-k identities
matched exactly and maximum top-k score error was `1.326e-09`. Native activation remains rejected
for list-shaped application vectors and accepted only for already-contiguous offline inputs.

## Work Package 8.5: Offline Packaging and Decision

- [x] Build the native library reproducibly in the application image
- [x] Inventory its source, compiler/build identity, binary checksum, and license/SBOM evidence
- [x] Prove the Phase 7 bundle still installs and operates without runtime compilation/downloads
- [x] Record final acceptance or rejection with fallback verification

The digest-pinned multi-stage image contains the 15,608-byte ABI-1 library and no compiler tools.
The successor 23-file bundle passed both verifiers and a clean seven-service, network-denied install.
Registration, ingestion, dense retrieval, grounded generation, packaged native loading, deliberate
Python fallback, and explicit API/web egress-denial probes all passed. The stack was stopped after
acceptance.

## Barebones Definition of Done

- [x] The C ABI is explicit, portable, sanitizer-clean, and directly tested
- [x] Python operation remains correct with and without the shared library
- [x] A deterministic report quantifies numerical error and boundary-inclusive performance
- [x] Any integration is reversible and excludes authorization/source-identity policy
- [x] The finalized offline bundle inventories the native binary and needs no build tools on target
