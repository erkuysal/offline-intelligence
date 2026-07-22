# Phase 9 Signing Foundation Acceptance

Date: 23 July 2026

Status: Accepted; WP9.2 complete

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

The dependency-free operator now requires a detached signature, externally provisioned public key,
and externally maintained revocation policy for `preflight` and `install`. It verifies bundle bytes
first, then signature identity and revocation, and returns before host probing or target mutation on
any trust failure. Focused coverage proves successful external-root verification, missing trust
material, revoked keys, and revoked releases; the signing tests additionally cover modified bundle
identities, modified signatures, and unknown public keys.

The retained WP9.1 bundle is an evidence-only provenance bundle and intentionally lacks the Compose
and environment payloads required by installation preflight. Its detached signature verifies, while
the full operator trust order is exercised with synthetic complete install bundles. A future promoted
release candidate must combine both boundaries before Phase 9 final acceptance.
