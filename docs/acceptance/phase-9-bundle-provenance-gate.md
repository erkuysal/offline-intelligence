# Phase 9 Bundle Provenance Gate Acceptance

Date: 23 July 2026

Status: Accepted; complete candidate generation remains in progress

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

This gate proves that construction cannot silently omit provenance. WP9.1 still requires a newly
built candidate whose specification covers all five runtime image archives, both GGUF models, all
five SPDX inventories, the native binding, and shared license evidence. No model server is required
for that construction work.
