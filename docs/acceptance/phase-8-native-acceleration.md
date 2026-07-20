# Phase 8 Native Acceleration Acceptance

Date: 20 July 2026

Status: Accepted

## Decision

Phase 8 accepts the optional C11 batch-cosine backend for already-contiguous offline evaluation and
experimental reranking. PostgreSQL/pgvector remains the production retrieval owner, and native
activation remains rejected for list-shaped application vectors because conversion cost erased the
kernel gain. The tested Python implementation remains the automatic fallback.

## Correctness and Performance

The deterministic verification gate compared 1,640 values across 200 fuzz cases with zero
failures. Maximum absolute error was `2.943e-08`, maximum relative error was `5.910e-08`, and both
Release and AddressSanitizer/UndefinedBehaviorSanitizer CTest runs passed.

The accepted bounded path ranked top 20 over 4,096 prepared float32 rows of 768 dimensions. Python
fallback measured `144.197` ms P50 and native scoring plus ranking measured `2.621` ms P50, a
`55.00x` speedup. Top-k identities matched exactly; maximum top-k score error was `1.326e-09`.

## Reproducible Image and Inventory

The application Dockerfile uses a digest-pinned `python:3.14-slim` base and a disposable builder
stage. GCC 14.2 and CMake 3.31.6 compile ABI version 1 in Release mode; only the 15,608-byte shared
library enters the runtime image. Runtime checks confirmed that `gcc`, `cmake`, and `make` are
absent.

The finalized identities are:

- image: `sha256:b4287f1c88c69914d3587159b14b243976aef74bd000f687b0a04edf8c25122f`;
- native binary: `e96f45b20bb7c637debe79fc8f692b582d357a80294b8df2d342e9e7afc4ad30`;
- deterministic native source archive:
  `5ea49b69595e9857d98a81f89cbbfbd6216e56debcd2176e97281e0381a4aa74`; and
- application image archive:
  `583d1208292905ce0411176444757f186661439b70298e040a677e54b5993aa7`.

The bundle includes the source archive, a machine-readable compiler/build/binary inventory, the
SPDX 2.3 application package inventory, and the repository's internal-distribution license status.
Docker Scout generated the 181-package inventory from the immediately preceding image with the
same runtime packages and native binary. The final rebuild only pinned the already-resolved base
digest and updated the Dockerfile copied into the image; the exact final image and binary hashes in
the native inventory are authoritative. No release metadata was uploaded again after the external
Scout indexing path was disallowed.

## Clean Offline Acceptance

The successor Phase 8 bundle contains 23 payload files and `3,400,787,185` payload bytes. Both the
library verifier and dependency-free operator verifier passed the exact-tree, checksum, required
payload, manifest-total, and network-policy gates.

A clean path-isolated install started seven healthy services from bundled images and local model
files. The application probe passed registration, login, upload, asynchronous ingestion, dense
retrieval, grounded local generation, and persisted document/citation checks in `1.399` seconds.
Inside the installed API image, the packaged backend reported native ABI 1; an intentionally
missing library selected the Python backend and returned identical test scores.

Network denial remained intact:

| Probe | Accepted outcome |
| --- | --- |
| API direct connection to `1.1.1.1:443` | `OSError: [Errno 101] Network is unreachable` |
| API resolution of `example.com` | `socket.gaierror: Temporary failure in name resolution` |
| Web request to `https://example.com` | `wget: bad address 'example.com'` |

The runtime log scan found only local listeners and internal calls to `llm:8080` and
`embedding:8080`. It found no download, telemetry, analytics, Sentry, Hugging Face, or other
external endpoint attempt. The stack, including both model servers, was stopped after acceptance;
the target evidence and volumes were preserved.

## Outcome

The native component improves one measured contiguous-data workload without replacing pgvector,
weakening the Phase 7 air-gap boundary, requiring target compilation, or removing portable
fallback operation. All Phase 8 barebones gates are accepted.
