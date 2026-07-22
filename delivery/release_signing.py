from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from delivery.release_source import sha256_file


class SigningError(ValueError):
    pass


class SignedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    payload_type: Literal["offline_bundle_release"] = "offline_bundle_release"
    release_id: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_size_bytes: int = Field(ge=0)
    checksums_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    checksums_size_bytes: int = Field(ge=0)


class SignatureEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    signature_type: Literal["offline_bundle_detached"] = "offline_bundle_detached"
    algorithm: Literal["Ed25519"] = "Ed25519"
    key_id: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    payload: SignedPayload
    signature_base64: str = Field(min_length=1)


def canonical_json(value: BaseModel) -> bytes:
    return (
        json.dumps(
            value.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def bundle_payload(bundle: Path) -> SignedPayload:
    bundle = bundle.expanduser().resolve()
    manifest = bundle / "manifest.json"
    checksums = bundle / "checksums.sha256"
    for path in (manifest, checksums):
        if path.is_symlink() or not path.is_file():
            raise SigningError(
                f"signed bundle input is not a regular file: {path.name}"
            )
    try:
        manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
        release_id = manifest_value["release_id"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SigningError(f"invalid bundle manifest: {exc}") from exc
    if not isinstance(release_id, str) or not release_id:
        raise SigningError("bundle manifest release_id is invalid")
    return SignedPayload(
        release_id=release_id,
        manifest_sha256=sha256_file(manifest),
        manifest_size_bytes=manifest.stat().st_size,
        checksums_sha256=sha256_file(checksums),
        checksums_size_bytes=checksums.stat().st_size,
    )


def run_openssl(arguments: list[str]) -> bytes:
    result = subprocess.run(["openssl", *arguments], check=False, capture_output=True)
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "OpenSSL failed"
        raise SigningError(detail)
    return result.stdout


def public_key_id(public_key: Path) -> str:
    if public_key.is_symlink() or not public_key.is_file():
        raise SigningError("public key must be a regular non-symlink file")
    der = run_openssl(["pkey", "-pubin", "-in", str(public_key), "-outform", "DER"])
    return f"sha256:{hashlib.sha256(der).hexdigest()}"


def sign_bundle(
    bundle: Path,
    private_key: Path,
    public_key: Path,
    *,
    passphrase_env: str | None = None,
) -> SignatureEnvelope:
    payload = bundle_payload(bundle)
    if private_key.is_symlink() or not private_key.is_file():
        raise SigningError("private key must be a regular non-symlink file")
    with tempfile.TemporaryDirectory(prefix="oih-sign-") as directory:
        payload_path = Path(directory) / "payload.json"
        payload_path.write_bytes(canonical_json(payload))
        arguments = [
            "pkeyutl",
            "-sign",
            "-rawin",
            "-in",
            str(payload_path),
            "-inkey",
            str(private_key),
        ]
        if passphrase_env:
            arguments.extend(["-passin", f"env:{passphrase_env}"])
        signature = run_openssl(arguments)
    return SignatureEnvelope(
        key_id=public_key_id(public_key),
        payload=payload,
        signature_base64=base64.b64encode(signature).decode("ascii"),
    )


def verify_bundle_signature(
    bundle: Path, envelope: SignatureEnvelope, public_key: Path
) -> None:
    observed_payload = bundle_payload(bundle)
    if observed_payload != envelope.payload:
        raise SigningError("signature payload does not match bundle identities")
    observed_key_id = public_key_id(public_key)
    if observed_key_id != envelope.key_id:
        raise SigningError(
            f"signature key mismatch: expected {envelope.key_id}, found {observed_key_id}"
        )
    try:
        signature = base64.b64decode(envelope.signature_base64, validate=True)
    except ValueError as exc:
        raise SigningError("signature is not valid base64") from exc
    with tempfile.TemporaryDirectory(prefix="oih-verify-") as directory:
        payload_path = Path(directory) / "payload.json"
        signature_path = Path(directory) / "signature.bin"
        payload_path.write_bytes(canonical_json(envelope.payload))
        signature_path.write_bytes(signature)
        run_openssl(
            [
                "pkeyutl",
                "-verify",
                "-rawin",
                "-in",
                str(payload_path),
                "-sigfile",
                str(signature_path),
                "-pubin",
                "-inkey",
                str(public_key),
            ]
        )


def write_signature(envelope: SignatureEnvelope, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(envelope.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
