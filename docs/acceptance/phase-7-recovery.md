# Phase 7 Recovery Acceptance

Date: 2026-07-19

Status: Accepted for WP7.4

## Scope

This acceptance covers same-release backup, independent verification, restore into an empty
path-isolated target, relationship validation, and data-preserving failure behavior. It does not
claim cross-release schema downgrade or automated upgrades.

## Recovery Set Contract

Each atomic backup contains a PostgreSQL custom dump, uploaded-file tar, sanitized configuration,
release identity, application version, Alembic revision, active model checksums, loaded image IDs,
a canonical manifest, and SHA-256 inventory. The backup directory and files are owner-private.
Target database/JWT secrets are excluded, but the backup remains sensitive because it contains
application data and password hashes.

Verification fails on tree drift, symlinks, byte-size or checksum mismatch, unsafe tar members,
target-secret metadata, public backup-directory permissions, or malformed inventory data.

## Real Drill

The source target contained user `backup-drill@local.test`, document
`documents/backup-drill.txt`, one related chunk, document status `ready`, and a 30-byte stored file
with SHA-256 `de3236e46dc4373a6ed5b083032f23574078b9c002db59740259d620b286f32c`.

The accepted private recovery set produced a 55,004-byte payload in 2.845 seconds and restored it in
6.239 seconds. The restored target reported Alembic revision `20260714_0013`; its joined
user/document/chunk query returned the original values, and the recovered file matched its database
size and checksum. PostgreSQL stopped after both operations.

A second restore into a populated target was rejected because 12 public tables already existed. No
LLM or embedding server was started during backup or restore. The accepted backup passed exact-tree,
payload-integrity, checksum-inventory, safe-storage, target-secret-absence, and private-permission
gates.

## Rollback Boundary

Rollback preserves the prior immutable bundle and a verified backup from that same release. Restore
rejects release, application, migration, model, or image identity mismatch. The accepted workflow
installs the retained prior bundle into a new target and restores its matching backup. In-place
Alembic downgrade and newer-database-to-older-application restore are intentionally unsupported.
