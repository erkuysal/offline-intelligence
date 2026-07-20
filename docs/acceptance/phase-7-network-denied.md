# Phase 7 Network-Denied Acceptance

Date: 20 July 2026

Status: Accepted

## Scope

This record closes WP7.5 and Phase 7. It covers one clean path-isolated installation from the real
Linux x86-64 CUDA bundle, the complete document-grounded user path, restart persistence, a verified
backup, empty-target restore, post-restore operation, and explicit outbound/DNS denial.

The adjacent `phase-7-network-denied.json` is the machine-readable acceptance summary. Per-run JSON
reports and the private backup remain under ignored `var/acceptance` and `var/backups` paths because
the test identity and restored application data are not release payloads.

## Accepted User Path

The dependency-free `operator/airgap_smoke.py` probe used a test-only credential supplied through an
environment variable; neither the password nor access/refresh tokens were written to its state or
reports. The clean seed run passed:

- registration and login;
- text upload and Redis-backed asynchronous ingestion to one ready chunk;
- dense retrieval of document `1`, including the exact `ORBIT-7429` marker, at normalized score
  `0.6854296718409782`;
- local grounded generation returning the marker and its persisted source; and
- direct reads of the persisted chunk, assistant message, and citation.

The seed sequence completed in `1.507` seconds. After a complete seven-service restart, the same
login, document, chunk, conversation, citation, retrieval result, and new grounded generation passed
in `0.331` seconds.

After the policy fix and deterministic bundle rebuild, a third fresh target was installed directly
from the finalized 21-file bundle. The smoke runner copied inside that bundle repeated the complete
seed path in `1.411` seconds; API and web DNS denial and direct API egress denial passed again.

## Recovery Path

The accepted WP7.5 backup has ID
`20260720T104504Z-offline-intelligence-hub-0.4.0-linux-x86_64`. It contains `60,772` payload bytes,
completed in `2.539` seconds, and independently passed exact-tree, checksum, storage-member,
target-secret-exclusion, and private-permission checks.

The source stack was stopped without deleting its data. Restore into a distinct empty target
completed in `6.354` seconds at migration `20260714_0013`. The original login, document/chunk,
conversation/citation, identical retrieval score, and new grounded local generation then passed.
The final accepted post-policy probe completed in `0.422` seconds.

## Network and Runtime Evidence

All seven final services were healthy and used only the bundled immutable images and local model
files. The accepted boundary is:

- an `internal: true` application bridge with no host-gateway aliases;
- a host-ingress edge bridge with IP masquerading disabled;
- no `NET_ADMIN` capability on web;
- one startup-only Docker DNS lookup for the internal `api` peer, followed by an `/etc/hosts` pin;
  and
- a loopback-only runtime resolver in web before nginx starts.

Controlled negative probes produced the required failures:

| Probe | Accepted outcome |
| --- | --- |
| API direct connection to `1.1.1.1:443` | `OSError: [Errno 101] Network is unreachable` |
| API resolution of `example.com` | `socket.gaierror: Temporary failure in name resolution` |
| Web request to `https://example.com` | `wget: bad address 'example.com'` |

The final 218-line runtime-log scan found seven URL-bearing lines. All seven were local listeners or
calls to `llm:8080` and `embedding:8080`; no download, telemetry, analytics, Sentry, Hugging Face, or
other external endpoint attempt appeared.

## Methodological Finding Fixed During WP7.5

The earlier edge policy blocked external connections but still allowed Docker's embedded resolver
to resolve an external name from web. Making the edge bridge Docker-internal also removed usable
host ingress, so that experiment was rejected. The accepted fix pins the one required internal peer
and disables DNS at runtime. This simultaneously preserves port 3000, removes the prior `NET_ADMIN`
requirement, and makes external name resolution fail closed.

## Decision

WP7.5 and the Phase 7 barebones definition of done are accepted. Phase 8 may add a native module only
as an explicitly inventoried, checksum-addressed bundle payload; it may not introduce runtime
downloads, external telemetry, unverified libraries, or a new egress path.
