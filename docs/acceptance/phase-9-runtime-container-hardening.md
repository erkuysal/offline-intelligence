# Phase 9 Runtime Container Hardening Acceptance

Date: 23 July 2026

Status: Accepted; WP9.3 complete

The production Compose policy applies to web, API, ingestion worker, Redis, PostgreSQL, and both
CPU/GPU variants of the chat and embedding services. Every runtime has a numeric non-root user,
read-only root filesystem, `cap_drop: [ALL]`, `no-new-privileges`, an init process, bounded PIDs,
memory, CPU, file descriptors, and rotated JSON logs. GPU services reserve one device by default.
Named data volumes and temporary filesystems are the only writable mounts; GGUF files remain
read-only.

Six deterministic policy tests cover the mandatory baseline, resource and log ceilings, explicit
writable paths, bounded GPU reservations, embedding batch capacity, and application-image users.
Both application images built successfully after the API switched to UID/GID `10001` and Nginx
switched to UID/GID `101`, port `8080`, and a non-root-safe main configuration.

An isolated `oih-wp93` Compose project proved a clean production first boot. PostgreSQL and Redis
initialized as UID `999`, Alembic reached `20260714_0013`, and the API, worker, web, database, and
queue health checks all passed. Live inspection confirmed the configured identities, read-only
roots, dropped capabilities, security option, PID/memory/CPU/nofile ceilings, and log rotation.
Writing to the API root filesystem failed while an authenticated Markdown upload succeeded in the
explicit document volume.

The normal backup paths also succeeded under hardening. PostgreSQL emitted a valid custom-format
archive with 114 table-of-contents entries, and the API one-off container emitted a safe storage
tar containing the uploaded document. These were diagnostic files in `/tmp`, not release backups.

After advance notice, the accepted local chat and embedding GGUF files were loaded by the two real
GPU services. Both ran as `65532:65532`, became healthy with read-only roots, reserved one GPU each,
and rejected a root-filesystem write. Application health routes returned `200`, and real chat
inference returned the requested response.

The first real document ingestion exposed a physical embedding batch of 512 tokens, smaller than
the configured 2,048-token context. The Compose commands now set both batch and micro-batch to
2,048 by default. Revalidation embedded the previously rejected 828- and 715-token chunks without
truncation; the document reached `ready` with two chunks and no ingestion error.

All real model services, application services, networks, and the three test-only named volumes were
stopped and removed after validation. No model server remains running.
