# Technical Vision v1 — Phase 7 Air-Gapped Delivery

Status: Future

## Intent

Turn a connected build into a complete, verifiable release that can be installed, operated,
upgraded, backed up, and restored on a target with no internet access.

## Trust Boundary

```text
Connected build environment
  ├── fetch pinned source dependencies
  ├── build images and model artifacts
  ├── produce SBOM, manifests, and checksums
  └── export signed/versioned release bundle
                    ↓ controlled transfer
Air-gapped target
  ├── verify before install
  ├── run without outbound network
  ├── expose only approved local interfaces
  └── support offline upgrade, backup, and restore
```

## Release Contents

- Container images and image inventory
- Offline Python and frontend dependency artifacts where required
- Pinned base model, adapter, embedding, reranker, and related manifests
- Database migrations and configuration templates
- Installation, verification, upgrade, rollback, backup, and restore tooling
- SHA-256 checksums, SBOM, license inventory, and provenance metadata
- Operator documentation and capacity requirements

## Proposed Module and Function Map

| Proposed command | Used for | Why it should be separate |
| --- | --- | --- |
| `build-offline-bundle` | Collects pinned release inputs into a staging tree | Prevents developer caches from becoming dependencies |
| `generate-manifest` | Records path, type, version, size, origin, and checksum | Creates an auditable machine-readable inventory |
| `verify-offline-bundle` | Recalculates checksums and checks completeness | Detects corruption, omission, and replacement before install |
| `preflight` | Validates architecture, disk, RAM/VRAM, ports, and runtime support | Fails before mutating an incompatible target |
| `install` | Loads images, writes configuration, and starts services | Makes installation repeatable and idempotent |
| `upgrade` / `rollback` | Applies versioned artifacts and migrations with recovery points | Treats upgrade failure as an expected case |
| `backup` / `restore` | Captures database, files, configuration metadata, and versions | Ensures all recovery state travels together |
| `airgap-smoke-test` | Exercises login, ingestion, retrieval, generation, and restart | Proves operation without network access |

## Integrity Calculations

```text
digest(path) = SHA256(all file bytes in order)
verified = constant_time_compare(expected_digest, calculated_digest)
missing = manifest_paths - bundle_paths
unexpected = bundle_paths - manifest_paths - allowed_operator_paths
```

Both path differences must be empty before installation. A checksum detects file changes but does
not prove publisher identity; if signatures are introduced, the canonical manifest and checksum
inventory should be signed together.

## Capacity Calculations

```text
required_disk = compressed_bundle + extracted_images + model_artifacts
                + database_growth_reserve + document_storage_reserve
                + backup_workspace + upgrade_rollback_reserve
```

Measured artifact sizes and configurable reserves drive preflight. Checking only archive size is
unsafe because installation may temporarily retain both compressed and extracted content.

## Backup and Recovery Calculations

A backup set couples PostgreSQL data, uploaded files, schema/migration version, active model and
adapter revisions, and required configuration metadata.

```text
RPO = maximum acceptable data loss measured backward from an incident
RTO = maximum acceptable time to restore service
```

Backup frequency is selected to meet RPO; restore automation, data size, and artifact availability
determine RTO. Acceptance requires a restore drill validating hashes, database relationships,
authentication, retrieval, and generation—not merely successful archive creation.

## Network-Denial Verification

Acceptance runs with outbound traffic blocked, fresh caches, and no external DNS assumption. Any
attempted outbound connection is a failure even if fallback succeeds, because it reveals an
incomplete privacy/offline contract.

## Operational Requirements

- No runtime downloads, external telemetry, DNS dependency, or hidden cache dependency
- Internal-only networks and least-privilege service identities
- Non-root containers and read-only filesystems where practical
- Explicit secret injection; no secrets in the bundle
- Preflight capacity and compatibility checks
- Idempotent installation and migration-aware upgrades
- Tested backup restoration, not merely backup creation
- Audit logs and local health/metrics access

## Expected Deliverables

- Phase 7 threat model and delivery plan
- Deterministic bundle builder and verifier
- Clean-machine, network-denied installation test
- Offline upgrade, rollback, backup, and disaster-recovery exercises
- Operations manual and acceptance record

## Dependency

The bundle incorporates the artifact and hardware decisions from Phases 5 and 6. Air-gap work may
expose reproducibility gaps in earlier phases; those gaps must be fixed at their source rather than
worked around with undocumented files.
