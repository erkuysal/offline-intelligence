# Technical Vision v1 — Phase 7 Air-Gapped Delivery

Status: Completed — clean network-denied operation and recovery accepted

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

The first implemented boundary is `delivery/offline_bundle.py`, exposed through
`offline-bundle-build` and `offline-bundle-verify`. It publishes a canonical manifest and checksum
inventory through an atomic staging rename and rejects tree drift, unsafe paths, symlinks, and
secret-bearing environment destinations before installation. The bounded execution sequence is
tracked in the [Phase 7 plan](../../plans/phase-7.md).

WP7.2 exercised that boundary with the real Linux x86-64 CUDA release inputs. The candidate contains
five image archives, pinned chat and embedding GGUF files, production Compose and secret-free
environment templates, deterministic migrations, dependency locks, five SPDX inventories, and an
explicit license-status record. Its 21 payload files total 3,400,687,736 bytes and verify with no
tree, size, or checksum failures.

WP7.3 uses the dependency-free `scripts/delivery/offline_operator.py` at the target boundary. It
re-verifies before mutation, gates host capacity and runtime support, creates target-only secrets,
loads only bundled archives, checks loaded image IDs, and invokes Compose with local-only build/pull
settings. Production services share an internal Docker network without host-gateway aliases. The
web service alone joins a non-masqueraded bridge for host ingress, pins its internal API peer, and
disables runtime DNS before nginx starts. Installations use target-derived Compose project names to
prevent accidental cross-target volume reuse.

The real WP7.3 run passed platform, Docker, Compose, RAM, VRAM, disk, and port preflight gates. A
small `/tmp` target correctly failed the disk formula before mutation; the intended high-capacity
filesystem passed. The installed stack reached seven healthy services, served chat and 768-value
embeddings locally, exposed only the web health route to the host, and denied outbound traffic from
both web and API. The bundled uninstall then stopped the stack while retaining files and volumes.

WP7.4 adds target-secret-excluding but sensitive-data-bearing recovery sets with a custom PostgreSQL
dump, uploaded-file archive, sanitized configuration, release/model/image/migration identities,
exact checksums, and private filesystem permissions. Restore requires an empty target with the exact
same release identity. The real drill recovered a database-linked document and matching stored-file
hash; retrying against the populated target failed closed.

WP7.5 completed the clean user-level path under that boundary. Registration, login, upload, queued
ingestion, dense retrieval, grounded generation, restart persistence, backup, empty-target restore,
and post-restore generation all passed. Direct API egress returned `ENETUNREACH`; external DNS
failed from API and web; and the runtime-log scan found only local service URLs with no download or
telemetry attempts. Machine-readable evidence is stored beside the
[WP7.5 acceptance record](../../acceptance/phase-7-network-denied.md).

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
