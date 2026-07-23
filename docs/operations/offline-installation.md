# Offline Bundle Installation

Status: WP7.4 operator and recovery contract

Phase 9 installations also require the detached signature, external public key, and external
revocation policy described in [Offline release signing](release-signing.md). Trust verification
completes before target mutation or image loading.

The operator tool is dependency-free Python and runs from the verified transfer directory. Python
3.11 or newer, Docker Engine with Compose v2, an NVIDIA driver/runtime, and sufficient local
capacity are target prerequisites. The target must not have internet access.

## Trust Procedure

Before connecting the transfer media to the target, obtain the expected SHA-256 of `manifest.json`
through a separately approved channel. On the target, compare that value first, then run:

```bash
python3 operator/offline_operator.py verify --bundle /media/offline-release
```

The command rejects malformed inventories, symlinks, missing or unexpected paths/directories,
size drift, checksum drift, and absent required production payloads. Do not install a bundle that
fails verification.

## Preflight

```bash
python3 operator/offline_operator.py preflight \
  --bundle /media/offline-release \
  --target /opt/offline-intelligence-hub \
  --output /tmp/offline-preflight.json
```

Defaults require Linux x86-64, Docker and Compose, 8 GiB available RAM, 6 GiB NVIDIA VRAM, port
3000, and free disk equal to twice the declared payload plus a 10 GiB operating reserve. Override
thresholds only from a documented capacity decision.

## Install

```bash
python3 operator/offline_operator.py install \
  --bundle /media/offline-release \
  --target /opt/offline-intelligence-hub
```

Installation always repeats verification and preflight before mutation. It atomically stages
Compose, the model files, release state, and a mode-0600 `config/prod.env`; database and JWT secrets
are generated locally and never copied from the transfer bundle. It then loads only `images/*.tar`,
checks every loaded tag against the immutable image IDs in the manifest, validates Compose, and
starts with `--no-build --pull never`.

Use `--no-start` to load and validate the installation without starting services. Repeating install
for the same release preserves secrets and fails if the installed Compose, example environment, or
model files drifted from the bundle.

The production application network is `internal: true` and has no host-gateway aliases. The web
container additionally joins a non-masqueraded edge bridge so Docker can publish the configured web
port. Before nginx starts, its entrypoint resolves only the internal `api` peer, pins that address
in `/etc/hosts`, and replaces runtime DNS with a loopback-only resolver. The web container does not
receive `NET_ADMIN`; edge masquerading remains disabled. Runtime downloads and external DNS are
outside the contract and must fail from both application and edge containers. Each target path also
receives a stable path-derived Compose project suffix so separate installations cannot silently
share volumes.

Run the dependency-free application probe from the bundle with a test-only password supplied by
environment variable. The JSON state contains identifiers but no tokens or password:

```bash
AIRGAP_SMOKE_PASSWORD='test-only-password' \
  python3 operator/airgap_smoke.py seed \
  --state /secure-reports/phase-7-state.json \
  --output /secure-reports/phase-7-seed.json
```

## Stop or Uninstall

```bash
python3 operator/offline_operator.py uninstall \
  --target /opt/offline-intelligence-hub
```

This runs Compose `down --remove-orphans` without `--volumes`. Named PostgreSQL, Redis, and document
storage volumes, target-generated secrets, models, and release state remain in place. Destructive
data removal is intentionally not part of the barebones operator command.

## Backup

```bash
python3 operator/offline_operator.py backup \
  --target /opt/offline-intelligence-hub \
  --output /secure-backups/offline-hub-20260719

python3 operator/offline_operator.py backup-verify \
  --backup /secure-backups/offline-hub-20260719
```

The backup command starts only PostgreSQL when a stopped target requires it and stops PostgreSQL
again afterward. It atomically publishes a mode-0700 directory containing a custom PostgreSQL dump,
a validated uploaded-file archive, sanitized configuration, release/model/image/migration
identities, a canonical manifest, and SHA-256 inventory.

Database and JWT secrets are excluded, so restore generates new credentials and invalidates prior
login tokens. Backups still contain password hashes, document content, account metadata, and other
sensitive application data. Treat them as confidential even though target secrets are excluded.

## Restore

Install the exact same bundle into a new target with `--no-start`, then run:

```bash
python3 operator/offline_operator.py restore \
  --backup /secure-backups/offline-hub-20260719 \
  --target /opt/offline-intelligence-hub-restored
```

Restore rejects checksum drift, unsafe archive members, identity mismatch, running targets,
nonempty PostgreSQL schemas, and nonempty document storage. It validates the recovered Alembic
revision, records duration, and stops PostgreSQL. If failure occurs after mutation begins, discard
that isolated target and retry with another empty target; never repair it in place.

## Upgrade and Rollback

Cross-release upgrade is fail-closed and limited to exact pairs in
`config/delivery/offline-upgrade-policy-v1.json`. The first supported pair is 0.4.0 to 0.5.0 at the
same Alembic revision, `20260714_0013`. Retain the exact signed target bundle, the exact prior
source bundle, and a fresh verified backup. The default policy rejects backups older than 24 hours,
an active source, an existing target path, an unsupported pair, an irreversible migration
boundary, or free space below twice the target payload plus the backup and 10 GiB reserve.

Stop the source after taking its backup, then verify without mutation:

```bash
python3 operator/offline_operator.py upgrade-preflight \
  --source-target /opt/offline-intelligence-hub-0.4.0 \
  --target /opt/offline-intelligence-hub-0.5.0 \
  --bundle /media/offline-release-0.5.0 \
  --backup /secure-backups/pre-0.5.0 \
  --policy config/delivery/offline-upgrade-policy-v1.json \
  --signature /media/trust/release.signature.json \
  --public-key /media/trust/release-public.pem \
  --revocation-policy /media/trust/revocations.json \
  --output /secure-reports/upgrade-preflight.json
```

Run `upgrade` with the same arguments after the report passes. The operator creates an isolated
blue/green target, verifies and loads only the signed target images, restores the source backup,
starts the target, and writes `upgrade.json`. A failed attempt removes only its newly created target
and target volumes; the stopped source and backup remain untouched.

Before accepting the new release, rollback remains available:

```bash
python3 operator/offline_operator.py rollback \
  --source-target /opt/offline-intelligence-hub-0.4.0 \
  --source-bundle /media/offline-release-0.4.0 \
  --target /opt/offline-intelligence-hub-0.5.0 \
  --backup /secure-backups/pre-0.5.0 \
  --policy config/delivery/offline-upgrade-policy-v1.json
```

Rollback verifies that the backup, source installation, source bundle, target evidence, and policy
all describe the same transition. It reloads the exact retained source images before restart, so
tag reuse cannot substitute target images for the prior release. It then checks the retained
database migration and records recovery duration. `upgrade-accept --target ...` permanently closes
this rollback window. Alembic downgrade and rollback across an irreversible migration remain
unsupported.

## Failure Semantics

- Exit `0`: requested verification or operation succeeded.
- Exit `1`: verification or preflight completed and a gate failed.
- Exit `2`: invocation, filesystem, Docker, Compose, identity, or installation error.

Do not work around failures with registry pulls, model downloads, placeholder secrets, or manual
manifest edits. Return to the connected build environment and produce a new release candidate.
