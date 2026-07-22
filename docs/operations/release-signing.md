# Offline Release Signing

Phase 9 uses a detached Ed25519 JSON envelope backed by OpenSSL. The signed canonical payload binds
the release ID and the SHA-256 and byte size of `manifest.json` and `checksums.sha256`. The envelope
travels beside the bundle; the trusted public key is provisioned separately and is never accepted
from the transfer media. Its key ID is the SHA-256 of the DER-encoded public key.

OpenSSL 1.1.1 or newer is required for Ed25519. Generate and encrypt a publisher key offline:

```bash
openssl genpkey -algorithm ED25519 -aes-256-cbc -out release-private.pem
openssl pkey -in release-private.pem -pubout -out release-public.pem
chmod 600 release-private.pem
```

Keep the encrypted private key and its passphrase in separate controlled storage. Back up both under
dual control and test recovery without using production transfer media. Provision the public key to
targets through an independently authenticated channel.

Sign and verify without placing secrets on the command line:

```bash
export OIH_SIGNING_KEY_PASSPHRASE='...'
./manage.py offline-bundle-sign --bundle offline-release \
  --private-key release-private.pem --public-key release-public.pem \
  --passphrase-env OIH_SIGNING_KEY_PASSPHRASE --output offline-release.signature.json
unset OIH_SIGNING_KEY_PASSPHRASE

./manage.py offline-bundle-signature-verify --bundle offline-release \
  --signature offline-release.signature.json --public-key /etc/oih/trust/release-public.pem
```

Rotate by provisioning the new public key before using its private counterpart. Record activation and
retirement dates and retain old public keys only for releases still supported. Revocation removes the
key ID from the target trust policy before any affected release is processed. If a private key or
passphrase may be exposed, stop signing, revoke its public key, generate a new pair, re-sign an
unchanged verified candidate, and preserve the incident and replacement key IDs. A lost key is
recovered only from the controlled backup; never regenerate a key under the same identity.
