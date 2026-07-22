# Technical Vision v1 — Phase 9 Production and Supply-Chain Hardening

Status: In progress — source and trust foundation accepted

## Intent

Make an accepted offline release authenticatable, locally inventoried, least-privileged, and safe to
upgrade. Phase 9 strengthens the delivery lifecycle; it does not change model behavior, retrieval
defaults, or the authorization boundary.

## Trust Flow

```text
clean source revision
  → pinned builders and local SBOM/provenance
  → canonical manifest and checksums
  → detached signature held outside the bundle
  → disconnected verification before mutation
  → least-privileged runtime
  → backup-aware upgrade or rollback
```

Integrity answers whether transferred bytes match the manifest. A detached signature additionally
answers whether an approved release key authorized that manifest. Neither substitutes for model
quality, application security, backup testing, or license review.

## Enduring Decisions

- Private image metadata must not be uploaded to an external indexing service merely to create an
  SBOM.
- The trust root is never shipped inside the same bundle it authenticates.
- Target verification occurs before loading images, writing configuration, or starting services.
- Runtime hardening must preserve uploads, migrations, health checks, model loading, and recovery.
- Upgrade safety is evidence-based and bounded by explicit migration compatibility.

The connected-builder/disconnected-target zones, asset classifications, mandatory failure actions,
and pre-mutation sequence are defined in the [Phase 9 release trust and threat
model](phase-9-threat-model.md). The first enforced gate binds release construction to a clean,
expected Git revision and rejects ignored cache or secret paths before Docker runs.

Project image Dockerfiles also accept explicit source-revision and source-date build arguments and
store them under distinct OCI/custom labels. The artifact-provenance verifier reads those labels
from the exported image config, verifies archive and SBOM subjects offline, and produces a stable
component-inventory digest without conflating image-index, platform-manifest, config, archive, and
SBOM identities.

## Evidence

Phase 9 produces versioned machine-readable records for provenance, SBOM identity, signature
verification, container policy, automated release gates, upgrade/rollback, and final disconnected
acceptance. Missing mandatory evidence is a rejection, not a warning.
