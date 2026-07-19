# Phase 7 Bundle Contract Acceptance

Date: 2026-07-19

Status: Accepted for WP7.0–WP7.4

## Outcome

The project now has a deterministic pre-installation trust boundary, a verified production bundle,
a working offline installation path, and accepted same-release recovery. It does not yet claim the
complete user-level network-denied acceptance sequence.

## Contract

Each input declares a source, normalized destination, artifact type, version, origin, optional
pre-pinned SHA-256, and an explicit no-secrets assertion. The builder copies regular files through a
temporary sibling directory, writes a canonical sorted manifest and checksum inventory, and
atomically publishes only into a previously absent output path.

Verification fails closed on:

- malformed or duplicate manifest records;
- absolute paths, traversal, reserved paths, or non-example environment files;
- symlinks at the bundle, manifest, checksum, or payload boundary;
- missing, unexpected, resized, or checksum-mismatched files;
- unexpected directories; and
- a checksum inventory that differs from the canonical manifest.

`offline-bundle-build` returns `2` for malformed specifications or build failures and `1` if the
newly built tree fails verification. `offline-bundle-verify` returns `1` for any integrity or
completeness failure and can write a machine-readable report outside the verified tree.

## Real Release Input Outcome

The accepted candidate is `offline-intelligence-hub-0.4.0-linux-x86_64`:

- 20 declared payload files totaling 3,400,671,316 bytes;
- API and ingestion worker image ID
  `sha256:9748b03d9cdeeea09df103d81eb9172549eff7eb649ddab3b78d6828cfb623c9`;
- web image ID `sha256:f6383f64e71b41b8d9ec9e05d8a0f9bbbd61ab929c08634982bbd88fe65e00c3`;
- pgvector image ID `sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc`;
- Redis image ID `sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99`;
- llama.cpp CUDA image ID
  `sha256:425eece82bbf514d99c482e3c1f011b460d493f09b1a2cdf9473ac9e0c2d7ee6`,
  built from revision `c198af4dc24f8e0ab8a569a60f931e03a192fd79` (build 9912); and
- chat and embedding GGUF SHA-256 values `8ccc5cd1...75a135` and
  `50d28e22...bccf26`, respectively.

Five Docker Scout SPDX reports cover the runtime images. The migration archive uses stable ordering,
timestamp, owner, and group metadata and explicitly excludes `__pycache__` and `*.pyc`; its audited
member list contains only Alembic configuration and tracked migration sources. Because the
repository has no top-level project license, the bundle explicitly records that this engineering
artifact does not grant external redistribution rights.

## Verification

- Nineteen filesystem-only tests pass, including exact-directory drift, symlink rejection,
  preflight gates, secret handling, idempotence, and data-preserving uninstall.
- Ruff and mypy pass for the bundle module and CLI surface.
- The real bundle passed independent exact-tree, byte-size, and SHA-256 verification with zero
  failures.
- The targeted suite passed in the project container: 11 tests in 0.06 seconds.
- Docker Desktop's host-forwarded PostgreSQL port rejected the host-side managed harness even while
  the container was healthy. Running through the Compose network removed that environmental layer
  and passed; this was not counted as a product failure.
- No LLM server, embedding server, or training process was required for WP7.0–WP7.2. Docker Scout
  used connected build-time metadata while producing the bundled SPDX reports; the target does not
  depend on it. WP7.3 explicitly started both bundled model servers after advance notice.

## WP7.3 Installation Outcome

The final target preflight passed Linux x86-64, Docker 29.6.1, Compose 5.3.0, available RAM, NVIDIA
VRAM, disk reserve, and port 3000 checks. A deliberate `/tmp` attempt failed before mutation because
the 16 GiB tmpfs did not meet the 17,538,673,528-byte capacity formula; targeting the project
filesystem passed with more than 950 GB free.

The bundled dependency-free operator then proved:

- mode-0600 target-generated database and JWT secrets with no example values retained;
- exact installed model checksums and immutable loaded-image identity checks;
- idempotent no-start installation without secret rotation or target drift;
- path-derived Compose project isolation between separate target directories;
- seven healthy production services using only bundled images and models;
- exact local chat response `offline-ready` and a 768-dimensional embedding response;
- reachable host health through port 3000;
- outbound denial from the gateway-less application network and from web after its edge default
  route is removed; and
- data-preserving uninstall with no `--volumes` operation.

The first internal-only network attempt correctly blocked egress but also prevented Docker Desktop
from publishing the web port. A non-masqueraded edge bridge restored ingress, but Docker Desktop
still provided egress; the accepted configuration therefore removes web's default route before
nginx starts. A policy check now rejects missing internal isolation, edge masquerading, route
lockdown, or any `host.docker.internal`/`extra_hosts` escape path.

One diagnostic rendered the first test target's generated environment values. That target was
immediately retired, its stack stopped, and the final acceptance used a new path-isolated target
with newly generated secrets. No exposed experimental credential is part of the accepted target.
