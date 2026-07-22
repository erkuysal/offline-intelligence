# Phase 9 Bundle Provenance Gate Acceptance

Date: 23 July 2026

Status: Accepted; WP9.1 complete

## Outcome

Offline bundle schema `1.1` makes a passing release-provenance specification mandatory. The bundle
builder refuses to create a staging tree unless provenance release metadata matches the bundle and
the provenance inventory exactly covers every declared container image, model, and SPDX payload.
Native inventories and model license evidence declared by provenance must also be shipped at their
declared paths.

For each covered payload, construction compares the independently observed provenance SHA-256 and
byte size with the exact source copied into the bundle. Any missing coverage, extra covered payload,
artifact-type substitution, checksum drift, size drift, failed source report, or failed artifact
identity check stops construction before the output directory is published.

## Embedded Evidence

The builder adds these generated, checksummed manifest records:

- `provenance/spec.json`, the exact specification used by the gate; and
- `provenance/report.json`, the canonical passing verification report.

The bundle manifest records the full source revision plus both provenance paths and SHA-256 values.
Offline bundle verification rechecks the embedded report's status, release ID, application version,
target architecture, source revision, specification digest, and every reported payload identity
against the manifest. This semantic check remains effective even if an internally consistent set of
manifest and checksum files is constructed around the wrong provenance metadata.

## Compatibility and Remaining Boundary

The bundle input schema intentionally advances from `1.0` to `1.1`; old specifications without a
provenance gate fail validation. Publisher authenticity is not claimed yet: WP9.2 will sign the
canonical manifest and checksum inventory with a trust root kept outside the transfer bundle.

## Complete Candidate Outcome

The exact clean source revision `154c725e70397b0b983dbf6889c633e15bd40d65` produced the first
complete WP9.1 candidate statement. Source preflight passed with 13 required files and zero forbidden
context paths. The statement passed for seven artifacts:

- application and web project images built with the exact source revision and epoch labels;
- pinned pgvector, Redis, and llama.cpp CUDA image archives;
- five SPDX 2.3 inventories generated locally with pinned Syft `1.48.0`;
- chat and embedding GGUF payloads with immutable revisions and shared checksum-bound license
  evidence; and
- the native vector-similarity binary bound to its application image and SPDX report.

Mandatory construction then produced and independently reverified a 16-file evidence bundle of
3,389,848,149 payload bytes. The bundle contains five images, five SPDX reports, two models, license
evidence, native inventory, and the generated provenance specification/report. No model server was
started, no model inference occurred, and no release tag was created.
