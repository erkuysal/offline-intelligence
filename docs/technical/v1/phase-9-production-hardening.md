# Technical Vision v1 — Phase 9 Production and Supply-Chain Hardening

Status: Next — begins after `v0.5.0` release closure

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

## Evidence

Phase 9 produces versioned machine-readable records for provenance, SBOM identity, signature
verification, container policy, automated release gates, upgrade/rollback, and final disconnected
acceptance. Missing mandatory evidence is a rejection, not a warning.
