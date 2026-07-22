# Phase 9 Source and Trust Foundation Acceptance

Date: 23 July 2026

Status: Accepted first slice; no release promotion claimed

## Accepted Scope

- The connected-builder, untrusted-transfer, disconnected-target, and out-of-band trust zones are
  documented and represented in a strict machine-readable policy.
- Release keys, trust roots, manifests, checksums, SBOM/provenance, images, models, backups, and
  operator secrets have explicit classifications and distribution boundaries.
- Missing, unknown, revoked, mismatched, or incomplete trust evidence has a fail-closed action.
- Nested Python caches, tool caches, dependency trees, and frontend build outputs are explicitly
  excluded from Docker contexts.
- A new `release-source-verify` command binds a clean source tree to a full Git revision, records
  required-file hashes, checks `.dockerignore`, and rejects ignored forbidden paths independently
  of Git status.
- A new `release-trust-policy-verify` command validates policy invariants, including builder-only
  private keys, out-of-band trust roots, and rejection before pre-install mutation.

## Commands

Validate the trust policy:

```bash
./manage.py release-trust-policy-verify
```

Run source preflight from a clean checkout, writing evidence under ignored release state:

```bash
./manage.py release-source-verify \
  --expected-revision "$(git rev-parse HEAD)" \
  --output var/release/source-preflight.json
```

The command intentionally fails in a normal development tree containing uncommitted changes,
ignored caches, dependency directories, local secrets, or generated frontend output. Release
construction must use a separate clean checkout rather than weakening the gate.

## Verification

- Ruff passed for the new modules, tests, and CLI surface.
- MyPy passed for both new delivery modules.
- Ten focused tests passed, covering clean source, wrong revision, tracked drift, ignored nested
  bytecode, missing ignore rules, JSON failure evidence, locale independence, policy structure,
  private-key containment, and mandatory failure rules.
- The complete PostgreSQL-backed backend suite passed all 332 tests.

## Remaining Boundary

This slice does not create image/model provenance statements, normalize SBOM output, eliminate
dependency-cache reliance, sign releases, or authorize target mutation. Those remain mandatory
WP9.1, WP9.2, and WP9.4 deliverables.
