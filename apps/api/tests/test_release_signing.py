import base64
import json
from pathlib import Path
import subprocess

import pytest

from delivery.release_signing import (
    SignatureEnvelope,
    SigningError,
    sign_bundle,
    verify_bundle_signature,
)


def write_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"release_id": "offline-hub-test"}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (bundle / "checksums.sha256").write_text("test inventory\n", encoding="utf-8")
    return bundle


def generate_keypair(tmp_path: Path, name: str) -> tuple[Path, Path]:
    private_key = tmp_path / f"{name}-private.pem"
    public_key = tmp_path / f"{name}-public.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_key)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        ],
        check=True,
        capture_output=True,
    )
    return private_key, public_key


def test_ed25519_detached_signature_verifies_offline(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    private_key, public_key = generate_keypair(tmp_path, "release")

    envelope = sign_bundle(bundle, private_key, public_key)

    verify_bundle_signature(bundle, envelope, public_key)
    assert envelope.algorithm == "Ed25519"
    assert envelope.key_id.startswith("sha256:")


def test_modified_bundle_identity_is_rejected(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    private_key, public_key = generate_keypair(tmp_path, "release")
    envelope = sign_bundle(bundle, private_key, public_key)
    (bundle / "checksums.sha256").write_text("changed\n", encoding="utf-8")

    with pytest.raises(SigningError, match="does not match bundle"):
        verify_bundle_signature(bundle, envelope, public_key)


def test_unknown_public_key_is_rejected(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    private_key, public_key = generate_keypair(tmp_path, "release")
    _other_private, other_public = generate_keypair(tmp_path, "other")
    envelope = sign_bundle(bundle, private_key, public_key)

    with pytest.raises(SigningError, match="key mismatch"):
        verify_bundle_signature(bundle, envelope, other_public)


def test_modified_signature_is_rejected(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    private_key, public_key = generate_keypair(tmp_path, "release")
    envelope = sign_bundle(bundle, private_key, public_key)
    signature = bytearray(base64.b64decode(envelope.signature_base64))
    signature[0] ^= 1
    envelope.signature_base64 = base64.b64encode(signature).decode("ascii")

    with pytest.raises(SigningError):
        verify_bundle_signature(bundle, envelope, public_key)


def test_signature_envelope_rejects_unknown_fields(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    private_key, public_key = generate_keypair(tmp_path, "release")
    payload = sign_bundle(bundle, private_key, public_key).model_dump(mode="json")
    payload["unexpected"] = True

    with pytest.raises(ValueError):
        SignatureEnvelope.model_validate(payload)
