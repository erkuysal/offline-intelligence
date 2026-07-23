# Phase 9 Upgrade and Rollback Acceptance

Date: 23 July 2026

Status: Accepted; WP9.5 complete

The dependency-free offline operator now supports an explicit blue/green transition from
`offline-intelligence-hub-0.4.0-linux-x86_64` to
`offline-intelligence-hub-0.5.0-linux-x86_64`. Both releases must use Alembic revision
`20260714_0013`; the policy declares no irreversible migration and permits rollback only before
operator acceptance.

Preflight verified the detached Ed25519 signature, external trust root and revocation policy,
source and target identities, stopped source, absent target, fresh matching backup, RAM, VRAM,
port, and disk capacity. It measured 921,890,639,872 free bytes against a 17,517,776,651-byte
upgrade requirement. The accepted backup was 44.489 seconds old against the 86,400-second maximum.
A stale but identity-correct backup discovered during diagnostics is now rejected by the explicit
freshness gate.

The forward-migration integration test started at migration `20260710_0008`, inserted a user,
document, conversation, and message, upgraded through `20260714_0013`, and verified the records,
retrieval metrics column, and lexical indexes. The production pair deliberately stays on the same
revision, so rollback does not require an Alembic downgrade.

After advance notice, the live upgrade started both real GPU model servers. The definitive
0.4.0-to-0.5.0 run completed in 55.792 seconds. Before cutover validation, the restored database
exactly matched the fresh source baseline: 1 user, 1 document, 1 document chunk, 1 conversation,
2 messages, and migration `20260714_0013`. API, LLM, and embedding health checks passed. A new user
then registered and logged in, and an authenticated request through the application returned
`upgrade path healthy` from model `local-chat`.

Rollback stopped the target, verified the retained source bundle against recorded source image,
model, application, and migration identities, reloaded the exact source images, and restarted
0.4.0 in 39.59 seconds. This exact reload is necessary because mutable Docker tags may have been
reassigned while loading the target bundle. The source returned healthy across web, API, LLM, and
embedding services. Its data again matched the pre-upgrade baseline exactly at 1/1/1/1/2 and
revision `20260714_0013`; target-only validation writes were correctly discarded with the
unaccepted blue/green target.

Restore also now permits image-provided empty directories while still rejecting every pre-existing
file or link in document storage. Failed upgrades remove only their newly created target and
volumes, leaving the stopped source and verified backup available for another attempt.

All real-model validation services were stopped after the proof. Final disconnected promotion and
the complete browser-led document-grounded workflow remain WP9.6.
