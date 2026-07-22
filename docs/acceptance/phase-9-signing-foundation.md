# Phase 9 Signing Foundation Acceptance

Date: 23 July 2026

Status: Signing foundation accepted; operator enforcement and revocation tests remain

The publisher can create and independently verify a strict detached Ed25519 envelope using OpenSSL.
It binds the exact canonical bundle manifest and checksum inventory, identifies the external public
key by its DER SHA-256, rejects unknown fields, and fails closed for changed payload identities,
modified signatures, and the wrong public key.

Five filesystem-only tests cover the successful path and these negative cases. The private key and
trusted public key are not written into the bundle. Operational guidance covers encrypted key
generation, separate storage, backup/recovery, rotation, compromise, and revocation.

The real WP9.1 evidence bundle was signed and verified with a disposable diagnostic key. The
retained external public key ID is
`sha256:09fe7c8cda110840f526f7efeaf925cc9a63959b5563b2ce7fd2e3f5ea4cd458`; the temporary private
key was removed immediately after proof. This is test evidence, not a production release identity.

The next slice must integrate the dependency-free operator so signature and revocation-policy checks
occur before target-directory creation, secret generation, image loading, or service startup.
