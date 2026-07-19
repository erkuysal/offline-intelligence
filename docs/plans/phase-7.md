# Phase 7 Barebones Air-Gapped Delivery Plan

Status: In progress — offline installation and recovery verified

## Scope Decision

Phase 7 will produce the smallest complete release that can be transferred to one Linux x86-64
target, verified before mutation, installed without internet access, backed up, and restored. The
accepted Phase 6 adapter-free Q4 CUDA profile remains unchanged. Multi-node deployment, automated
signing infrastructure, and zero-downtime upgrades are deferred until after Phase 8.

## Work Package 7.0: Trust Boundary and Threat Model

- [x] Separate connected build actions from disconnected target actions
- [x] Require explicit file inventory, provenance, version, byte size, and SHA-256
- [x] Reject secrets, path traversal, symlinks, missing files, unexpected files, and unexpected
  directories at the verification boundary
- [x] Keep runtime model downloads and mutable developer caches outside the target contract

The transfer bundle proves integrity and completeness, not publisher identity. A detached signature
can be added later; the initial trust procedure compares the manifest checksum through a separate
approved channel. Secrets are created or injected on the target and never included in the bundle.

## Work Package 7.1: Deterministic Bundle Contract

- [x] Define a strict versioned bundle specification and manifest
- [x] Build through a same-filesystem staging directory and atomic rename
- [x] Generate a canonical manifest and `checksums.sha256`
- [x] Verify exact tree shape, regular-file policy, sizes, and constant-time checksum equality
- [x] Make invalid or corrupted bundles return non-zero status before installation
- [x] Add deterministic fake/static tests

Implemented commands:

```bash
./manage.py offline-bundle-build --spec bundle-spec.json --output offline-release
./manage.py offline-bundle-verify --bundle offline-release --output verification.json
```

`config/delivery/offline-bundle-v1.example.json` defines the GPU bundle inventory, pins both
accepted model checksums, and records locally built images by immutable image ID plus exported
archive checksum. Its generated sources remain under ignored `var/release-inputs`.

## Work Package 7.2: Reproducible Release Inputs

- [x] Pin and export the API, web, PostgreSQL/pgvector, Redis, and CUDA llama.cpp images
- [x] Include the accepted generation and embedding GGUF files with their immutable identities
- [x] Include production Compose, migrations, secret-free configuration templates, licenses, and a
  minimal SBOM/inventory
- [x] Prove bundle construction does not depend on unlisted cache files

Accepted release candidate: `offline-intelligence-hub-0.4.0-linux-x86_64`, containing 20 payload
files and 3,400,671,316 payload bytes. Exact-tree verification passed with zero failures. Migration
packaging explicitly excludes Python bytecode caches; all other content is copied only from the
strict input list. The repository has no top-level project license, so the bundle carries an
explicit internal-distribution status record and SPDX inventories rather than implying
redistribution rights.

## Work Package 7.3: Target Preflight and Installation

- [x] Check Linux architecture, disk reserve, RAM/VRAM, NVIDIA/container runtime, ports, and Docker
- [x] Load only bundled images and configure local model paths
- [x] Require target-generated secrets and fail if examples/defaults remain active
- [x] Start idempotently with outbound networking denied
- [x] Provide a clean uninstall that preserves operator data by default

The dependency-free bundled operator passed real preflight and install runs. It generated mode-0600
target secrets, loaded and identity-checked only bundle archives, and preserved those secrets during
a repeated no-start install. The final start produced seven healthy services, chat returned the
required local response, embeddings returned 768 dimensions, the host web health route worked, and
outbound requests failed from both the internal API and edge web containers. Uninstall stopped all
services without deleting named volumes, models, configuration, secrets, or release state.

## Work Package 7.4: Backup, Restore, and Rollback

- [x] Couple PostgreSQL dump, uploaded files, configuration metadata, migration revision, and active
  model identities into one checksum-indexed backup set
- [x] Restore into an empty target and validate database/file relationships
- [x] Preserve the prior release and document a migration-aware rollback boundary
- [x] Record measured backup and restore duration for the local test dataset

The real drill backed up a seeded user/document/chunk relationship and its 30-byte stored file,
verified the backup independently, restored it into separate path-isolated targets, and matched the
database checksum to the restored file. The accepted private recovery set contained 55,004 payload
bytes and took 2.845 seconds; restore completed in 6.239 seconds at migration `20260714_0013`. A
repeated restore into a populated target failed closed with 12 public tables.

## Work Package 7.5: Network-Denied Acceptance

- [ ] Install from a clean target state with external DNS and outbound traffic unavailable
- [ ] Exercise login, upload, ingestion, retrieval, generation, restart, backup, and restore
- [ ] Fail on any attempted runtime download or external telemetry connection
- [ ] Store machine-readable smoke and acceptance reports

## Barebones Definition of Done

- [x] A connected build produces one complete, deterministic, secret-free release directory
- [ ] A disconnected target verifies the release before installation
- [x] The accepted Q4 and embedding models serve only from bundled local files
- [ ] Production services start and pass the application smoke path without outbound access
- [x] A real backup restores successfully into an empty target
- [ ] Phase 8 can add a native module without weakening the offline bundle contract

## Deferred Until After Phase 8

- Detached signing service, hardware-backed keys, and organizational PKI
- Multi-architecture and multi-node bundles
- Zero-downtime/rolling upgrades and high availability
- Full artifact-registry mirroring
- Automated fleet orchestration
