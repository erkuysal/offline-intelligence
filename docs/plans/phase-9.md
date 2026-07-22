# Phase 9 Production and Supply-Chain Hardening Plan

Status: In progress — WP9.0 accepted, WP9.1 underway

## Intent

Phase 9 converts the accepted single-host barebones system into a stronger production release
process. It improves publisher authenticity, artifact provenance, container isolation, automated
release gates, and upgrade safety without changing model behavior or retrieval defaults.

## Scope Boundaries

Phase 9 includes one Linux x86-64 CUDA release line and one operator-managed deployment. Model-tier
routing, new LLMs, new adapters, desktop packaging, voice, high availability, multi-node operation,
and fleet orchestration remain outside this phase.

## Work Package 9.0: Release Baseline and Threat Review

- [x] Accept and tag `v0.5.0` as the immutable hardening baseline; retain the documented clean-tag
      artifact reproducibility gap as a mandatory hardening input
- [x] Update the connected-builder/disconnected-target threat model
- [x] Classify release keys, manifests, SBOMs, images, models, backups, and operator secrets
- [x] Define failure behavior for missing, expired, revoked, or mismatched trust material

No LLM servers are required.

## Work Package 9.1: Local SBOM and Provenance

- [x] Pin a fully local SBOM generator by version and checksum
- [x] Generate SPDX inventories without remote indexing
- [x] Bind SBOMs to scoped image identities, source revision, Dockerfile digest, and native binary
      checksum through the offline artifact-provenance verifier
- [ ] Produce a machine-readable provenance statement for every shipped image and model
- [ ] Fail release construction when inventory identity and payload identity differ

No LLM servers are required.

The accepted foundation is recorded in
[the Phase 9 source/trust acceptance](../acceptance/phase-9-source-trust-foundation.md). The source
preflight closes the `v0.5.0` dirty-context failure mode; cache-independent artifact construction,
canonical SBOM/image identity, and artifact provenance remain active WP9.1 work.

The verifier and identity model are recorded in
[the artifact-provenance foundation acceptance](../acceptance/phase-9-artifact-provenance-foundation.md).
A complete candidate specification covering every shipped image and model, followed by mandatory
bundle integration, is still required before the remaining WP9.1 items can close.

## Work Package 9.2: Signing and Verification

- [ ] Select a detached-signature format with offline verification support
- [ ] Document key generation, encrypted storage, rotation, revocation, backup, and recovery
- [ ] Sign the canonical release manifest and checksum inventory
- [ ] Verify signatures before target mutation or image loading
- [ ] Add negative tests for unknown keys, modified manifests, wrong releases, and revoked keys

Hardware-backed keys and organizational PKI may be added later; the initial implementation must
keep the trust root outside the transfer bundle. No LLM servers are required.

## Work Package 9.3: Runtime Container Hardening

- [ ] Run API, worker, web, Redis, PostgreSQL, and model services as non-root where compatible
- [ ] Add read-only root filesystems and explicit writable mounts where practical
- [ ] Drop unused Linux capabilities and enforce `no-new-privileges`
- [ ] Bound PID, memory, CPU, GPU, file-descriptor, and log growth
- [ ] Verify health checks, backups, migrations, model loading, and uploads under the hardened policy

Model-server validation is required after policy changes; the operator must be informed before
those services start.

## Work Package 9.4: Automated Release Gates

- [ ] Build release inputs from a clean checkout with no unlisted cache dependency
- [ ] Automate backend, frontend, native, bundle, SBOM, signature, and policy validation
- [ ] Emit one machine-readable release decision containing every required gate
- [ ] Preserve logs and reports without tokens, passwords, document text, or private prompts
- [ ] Fail closed on missing evidence or skipped mandatory gates

Deterministic gates use fake model backends. Final promotion acceptance starts both real model
servers and requires advance notice.

## Work Package 9.5: Upgrade and Rollback

- [ ] Define supported source and target release pairs
- [ ] Verify pre-upgrade backup and free-space requirements
- [ ] Exercise forward migrations against representative persisted data
- [ ] Prove rollback before irreversible migration boundaries
- [ ] Record recovery time, data integrity, and application behavior after upgrade and rollback

The final application path uses both real model servers and requires advance notice.

## Work Package 9.6: Acceptance

- [ ] Verify signed transfer on a clean disconnected target
- [ ] Install and operate with hardened container policies and outbound networking denied
- [ ] Exercise the complete document-grounded path, restart, backup, upgrade, rollback, and restore
- [ ] Record residual risks, deferred controls, and the final production-hardening decision

## Definition of Done

- [ ] A target authenticates the publisher and verifies exact artifact integrity before mutation
- [ ] SBOM and provenance generation is local, pinned, reproducible, and bound to shipped identities
- [ ] Runtime services operate with documented least-privilege controls
- [ ] Mandatory release evidence is produced automatically and fails closed when incomplete
- [ ] A supported upgrade and rollback path preserves accepted application behavior and data
