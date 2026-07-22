# Phase 9 Release Trust and Threat Model

Status: Accepted foundation — signing and canonical artifact identity remain in progress

Date: 23 July 2026

## Security Objective

A disconnected target must authenticate the release publisher, verify the exact release tree and
payload identities, and emit an allow/reject decision before loading images, writing production
configuration, running migrations, replacing release state, or starting services.

This model covers the release lifecycle from a connected builder through untrusted transfer media
to one operator-managed disconnected target. It does not claim that a compromised build host can
produce trustworthy artifacts, that checksums prove publisher identity, or that release signing
replaces application security, model-quality evaluation, backup testing, or license review.

The enforceable asset classifications and failure rules are defined in
[`release-trust-policy-v1.json`](../../../config/supply-chain/release-trust-policy-v1.json).

## Trust Zones

| Zone | Trust granted | Trust explicitly denied |
| --- | --- | --- |
| Connected builder | Clean source checkout, pinned input acquisition, construction, local inventory, release signing | Runtime-secret packaging and remote disclosure of private image metadata |
| Transfer media | Byte transport after construction | Publisher identity, integrity assertions, and trust-root provisioning |
| Disconnected target | Verification against separately provisioned trust material, installation, runtime, backup, and recovery | Network retrieval of missing evidence and loading unverified images |
| Trust administration | Out-of-band public trust-root and revocation-policy provisioning | Shipping the trust root inside the bundle it authenticates |

Transfer media, bundle filenames, image tags, manifest fields, SBOM labels, and operator-supplied
paths are untrusted until they have been checked against authenticated identities.

## Asset Classification

| Asset | Classification | Permitted location | Authority |
| --- | --- | --- | --- |
| Release-signing private key | Secret | Connected builder only | Release owner |
| Release public trust root | Public, integrity-critical | Target trust store provisioned out of band | Trust administrator |
| Canonical manifest and checksums | Public, integrity-critical | Transfer bundle | Release pipeline |
| SBOM and provenance | Internal, integrity-critical | Transfer bundle | Release pipeline |
| Container images and models | Internal, integrity-critical | Transfer bundle | Release/model owner |
| Backup archives | Confidential and integrity-critical | Target only | Target operator |
| Runtime/database/JWT secrets | Secret | Target only | Target operator |

Secret or confidential material is never a legal release-bundle input. The signing private key is
not a runtime secret and must never reach the disconnected target. The public trust root may be
copied to the target, but never through the same unauthenticated channel as the release it verifies.

## Threats and Mandatory Responses

| Threat or failure | Detection boundary | Required response |
| --- | --- | --- |
| Dirty or wrong source revision | Before image construction | Halt and emit failed source-preflight evidence |
| Host caches or local secrets in the Docker context | Before image construction | Halt and identify every forbidden path |
| Missing provenance or mismatched SBOM identity | Before bundle construction | Halt; do not create a promotable bundle |
| Modified manifest or checksum inventory | Target pre-installation | Reject before mutation |
| Missing signature, unknown key, or revoked key | Target pre-installation | Reject before mutation |
| Release ID copied from another signed release | Target pre-installation | Reject before mutation |
| Added, removed, substituted, or truncated payload | Target pre-installation | Reject before mutation |
| Missing trust or revocation policy | Target pre-installation | Reject; never retrieve it from the network |
| Upgrade or rollback identity mismatch | Upgrade boundary | Halt and require verified recovery/restore evidence |

Failures are terminal for the attempted operation. “Continue with warning,” fetching replacement
evidence, accepting a checksum from the bundle itself as authority, and loading images for later
inspection are prohibited fallbacks.

## Pre-Mutation Sequence

The target must complete these operations in order:

1. Load the out-of-band trust root and applicable revocation policy.
2. Parse the release envelope using strict, bounded schemas.
3. Verify the detached signature over the canonical manifest/checksum identity.
4. Verify the exact bundle tree, file sizes, and payload checksums.
5. Bind release, source, provenance, SBOM, image, model, native, and migration identities.
6. Emit one machine-readable pre-install decision.

Only a complete passing decision may authorize image loading or any other target mutation. Later
work packages implement steps 3, 5, and 6; Phase 7 already supplies the exact-tree and payload
integrity checks used by step 4.

## Clean-Source Boundary

[`release-source-v1.json`](../../../config/supply-chain/release-source-v1.json) defines the first
enforced Phase 9 gate. `release-source-verify` requires a full expected Git SHA, verifies a clean
repository root, records the commit timestamp as `SOURCE_DATE_EPOCH` input, hashes mandatory build
files, checks required nested `.dockerignore` rules, rejects symlinks, and independently scans for
ignored caches or local secrets that Git status would not report.

The report is canonical, machine-readable JSON. A mismatch returns a nonzero status and lists the
failed conditions. Outputs belong under ignored `var/` paths so evidence generation cannot dirty
the source tree it evaluates.

## Residual Risks and Next Controls

- Release signing and revocation enforcement are specified but not implemented.
- A clean source context does not yet prove independence from local BuildKit dependency caches.
- Canonical OCI, archive, and normalized SPDX identity boundaries remain undefined.
- The connected builder remains a high-trust system; compromise requires key revocation and a new
  clean build on a restored builder.
- Hardware-backed signing keys and organizational PKI remain optional future controls.

These are mandatory inputs to WP9.1, WP9.2, and WP9.4, not accepted exceptions to the final Phase 9
release decision.
