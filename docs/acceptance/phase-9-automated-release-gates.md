# Phase 9 Automated Release Gates Acceptance

Date: 23 July 2026

Status: Accepted; WP9.4 complete

The `release-gate-verify` command now turns the release controls from WP9.0 through WP9.3 into one
ordered, machine-readable decision. Its strict schema requires exactly source, backend, frontend,
native, bundle, SBOM/provenance, signature, and container-policy gates. The runner snapshots clean
source before executing commands, forces fake model backends, runs cleanup even after failure, and
blocks all later gates after the first mandatory failure.

The decision and metadata log retain command status, timing, output sizes and SHA-256 identities,
and declared evidence identities. Child stdout and stderr are never persisted. Inline code,
credential-shaped arguments, and authenticated URLs are redacted. No document text, private prompt,
token, password, authorization value, or private key is required in a decision or log.

Candidate coherence is enforced across stages. The verified bundle manifest and passing provenance
report must carry the gate specification's exact release ID and full Git revision. The independently
verified detached signature must name that release. This closes the stale-candidate gap where valid
older artifacts might otherwise be combined with newer source tests.

Nine focused tests cover a complete pass, missing mandatory gates, semantically skipped checks,
command failure and downstream blocking, missing evidence, dirty source rejection before execution,
candidate identity mismatch, metadata redaction, and cleanup after failure. A CLI negative proof
against the intentionally dirty development tree returned `fail`, recorded all eight gates, and
marked all command gates `not_run` without starting Docker or model services.

The version-controlled example automates the established backend suite/lint/type gate, frontend
install/unit/type/build gate, native CMake/CTest gate, bundle verification, provenance/SBOM
verification, detached-signature verification, production Compose policy, and release trust-policy
validation. Backend PostgreSQL and Redis use an isolated Compose project whose cleanup removes its
test-only volumes.

No real model server is used by this deterministic work package. Final promotion acceptance remains
the boundary that starts both servers after advance notice.
