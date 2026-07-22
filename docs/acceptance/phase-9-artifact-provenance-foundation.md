# Phase 9 Artifact Provenance Foundation Acceptance

Date: 23 July 2026

Status: Verifier and bundle enforcement accepted; candidate-wide provenance remains in progress

## Accepted Scope

The new `release-provenance-verify` command consumes a passing source-preflight report and a strict
artifact specification. It emits canonical machine-readable JSON and fails closed when any declared
identity cannot be independently verified.

For project-built images, the verifier binds:

- the full source revision and deterministic source-date epoch;
- the Dockerfile path and SHA-256 recorded by source preflight;
- required OCI source labels stored in the image configuration;
- exact `docker save` archive SHA-256, byte size, repository tags, and config digest;
- raw SPDX SHA-256, package count, and Syft subject platform-manifest identity;
- a normalized component-inventory digest that excludes volatile SPDX document metadata; and
- optional native inventory, binary, image-index, and SBOM identities.

External images bind their archive/config/SBOM identities to an explicit immutable upstream
reference without claiming they were built from the application source revision. GGUF models bind
their exact payload identity to the declared upstream model revision and the checksum and size of
bundled license evidence.

Run the verifier after image export, local SBOM generation, and source preflight:

```bash
./manage.py release-provenance-verify \
  --spec var/release/provenance-spec.json \
  --output var/release/artifact-provenance.json
```

The checked-in
[`release-provenance-v1.example.json`](../../config/supply-chain/release-provenance-v1.example.json)
documents the strict input shape without claiming example zero digests are releasable identities.

## Identity Boundaries

The verifier deliberately keeps these identities separate:

| Identity | Meaning |
| --- | --- |
| Image index SHA-256 | Outer BuildKit/OCI image identity recorded by the builder |
| Image config SHA-256 | Configuration object embedded and independently verified in the archive |
| SBOM subject manifest SHA-256 | Platform-manifest identity recorded by Syft's OCI package URL |
| Archive SHA-256 | Exact bytes transferred in the offline bundle |
| Normalized component inventory SHA-256 | Stable dependency inventory excluding timestamps, namespaces, and the container subject |

Treating one of these values as an alias for another is rejected by the contract design.

## Verification Coverage

Eleven focused tests cover successful project-image/native/model binding, external-image binding,
wrong source labels, payload drift, SBOM subject substitution, native image substitution, stable
SPDX normalization, symlinked evidence, model-license drift, strict example validation, and
machine-readable failed reports.

## Remaining Boundary

`offline-bundle-build` now makes provenance mandatory as recorded in the
[bundle provenance gate acceptance](phase-9-bundle-provenance-gate.md). Generating a complete
specification for every image and model in a new candidate and signing the resulting report remain
WP9.1/WP9.2 work. No current release artifact is promoted by this foundation acceptance.
