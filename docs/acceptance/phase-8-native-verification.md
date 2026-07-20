# Phase 8 WP8.3 Native Verification Acceptance

Date: 20 July 2026

Status: Correctness and memory safety accepted; list-boundary performance rejected

## Scope

This gate verifies scalar ABI version `1`, the `ctypes` binding, deterministic numerical
equivalence, invalid-input behavior, sanitizer execution, and boundary-inclusive performance. It
does not authorize production retrieval activation.

## Correctness and Safety

- Release and debug CMake builds passed with `-Wall -Wextra -Wpedantic -Werror`.
- CTest passed with AddressSanitizer and UndefinedBehaviorSanitizer.
- LeakSanitizer was disabled because it cannot run under the local ptrace wrapper; the C library
  performs no allocation.
- C tests cover null pointers, empty inputs, multiplication overflow, zero norms, NaN, infinity,
  float32 extremes, dot/norm/cosine, batch output, ABI, and build metadata.
- Seed `82026` produced 200 deterministic cases and 1,640 compared values.
- Tolerances: absolute `1e-6`, relative `1e-5`.
- Failures: `0`.
- Maximum absolute error: `2.9427882020094387e-08`.
- Maximum relative error: `5.910075076320368e-08`.

The accepted Release library SHA-256 is
`b60331a70537fb355fb0decd548adfeddfd9a60ca6942ed7cb47da14edd6bfc3`; its capability string is
`abi=1;implementation=scalar;c_standard=11;compiler=gcc-15.2`.

## Boundary-Inclusive Performance

| Dimensions | Batch | Fallback mean ms | Conversion mean ms | Kernel mean ms | Kernel speedup | Boundary mean ms | Boundary speedup |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 768 | 1 | 0.034 | 0.071 | 0.003 | 12.54x | 0.075 | 0.45x |
| 768 | 32 | 0.829 | 1.174 | 0.022 | 37.88x | 1.241 | 0.67x |
| 768 | 256 | 6.331 | 9.135 | 0.157 | 40.25x | 9.240 | 0.69x |
| 1536 | 32 | 1.564 | 2.286 | 0.040 | 38.68x | 2.330 | 0.67x |

The C computation is materially faster, but converting nested Python lists into contiguous float32
buffers costs more than the full Python calculation. The current application and embedding clients
produce list-shaped vectors, so activating this boundary there would be a regression.

## Decision

Accept numerical correctness, ABI behavior, sanitizer evidence, and the Python fallback. Reject
list-based runtime promotion. WP8.4 may evaluate one already-contiguous offline path; it must retain
the fallback and must be rejected if upstream buffer production/conversion erases the kernel gain.
