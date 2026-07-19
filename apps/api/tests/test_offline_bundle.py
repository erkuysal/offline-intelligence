import argparse
import hashlib
import json
from pathlib import Path

import pytest

import manage
from delivery.offline_bundle import (
    BundleError,
    BundleSpec,
    build_offline_bundle,
    verify_offline_bundle,
)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_spec(tmp_path: Path, *, checksum: str | None = None) -> Path:
    model = b"fake-gguf-model"
    (tmp_path / "model.gguf").write_bytes(model)
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    payload = {
        "schema_version": "1.0",
        "spec_type": "offline_bundle_spec",
        "release_id": "offline-hub-0.4.0-test",
        "app_version": "0.4.0",
        "target_architecture": "linux-x86_64",
        "inputs": [
            {
                "source": "model.gguf",
                "path": "models/chat-model.gguf",
                "artifact_type": "model",
                "version": "q4-test",
                "origin": "test/model",
                "expected_sha256": checksum or digest(model),
                "contains_secrets": False,
            },
            {
                "source": "compose.yaml",
                "path": "configs/compose.yaml",
                "artifact_type": "configuration",
                "version": "0.4.0",
                "origin": "repository",
                "contains_secrets": False,
            },
        ],
    }
    spec = tmp_path / "bundle-spec.json"
    spec.write_text(json.dumps(payload), encoding="utf-8")
    return spec


def test_builder_creates_deterministic_self_verifying_bundle(tmp_path: Path) -> None:
    spec = write_spec(tmp_path)
    first = tmp_path / "bundle-one"
    second = tmp_path / "bundle-two"

    first_manifest = build_offline_bundle(spec, first)
    second_manifest = build_offline_bundle(spec, second)

    assert first_manifest == second_manifest
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    assert (first / "checksums.sha256").read_bytes() == (
        second / "checksums.sha256"
    ).read_bytes()
    report = verify_offline_bundle(first)
    assert report.passed is True
    assert report.verified_file_count == 2
    assert report.total_size_bytes == len(b"fake-gguf-model") + len(b"services: {}\n")


@pytest.mark.parametrize("mutation", ["changed", "missing", "unexpected", "unexpected_directory"])
def test_verifier_fails_closed_on_bundle_tree_drift(tmp_path: Path, mutation: str) -> None:
    bundle = tmp_path / "bundle"
    build_offline_bundle(write_spec(tmp_path), bundle)
    if mutation == "changed":
        (bundle / "models" / "chat-model.gguf").write_bytes(b"changed")
    elif mutation == "missing":
        (bundle / "models" / "chat-model.gguf").unlink()
    elif mutation == "unexpected":
        (bundle / "untracked.txt").write_text("unexpected", encoding="utf-8")
    else:
        (bundle / "empty-untracked-directory").mkdir()

    report = verify_offline_bundle(bundle)

    assert report.passed is False
    expected_failure = {
        "changed": "mismatch",
        "missing": "missing file",
        "unexpected": "unexpected file",
        "unexpected_directory": "unexpected directory",
    }[mutation]
    assert any(expected_failure in failure for failure in report.failures)


def test_verifier_rejects_symlinks_even_when_the_target_is_valid(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    build_offline_bundle(write_spec(tmp_path), bundle)
    model = bundle / "models" / "chat-model.gguf"
    model.unlink()
    model.symlink_to(bundle / "configs" / "compose.yaml")

    report = verify_offline_bundle(bundle)

    assert report.passed is False
    assert "symlink is not allowed: models/chat-model.gguf" in report.failures


def test_builder_rejects_source_checksum_mismatch_without_partial_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "bundle"

    with pytest.raises(BundleError, match="checksum mismatch"):
        build_offline_bundle(write_spec(tmp_path, checksum="0" * 64), output)

    assert not output.exists()


@pytest.mark.parametrize("path", ["../secret.env", "/absolute/file", "configs/prod.env"])
def test_spec_rejects_unsafe_or_secret_destinations(tmp_path: Path, path: str) -> None:
    payload = json.loads(write_spec(tmp_path).read_text(encoding="utf-8"))
    payload["inputs"][0]["path"] = path

    with pytest.raises(ValueError):
        BundleSpec.model_validate(payload)


def test_cli_returns_nonzero_for_corrupt_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    build_offline_bundle(write_spec(tmp_path), bundle)
    (bundle / "configs" / "compose.yaml").write_text("corrupt", encoding="utf-8")
    report_path = tmp_path / "verification.json"

    status = manage.offline_bundle_verify(
        argparse.Namespace(bundle=str(bundle), output=str(report_path))
    )

    assert status == 1
    assert json.loads(report_path.read_text(encoding="utf-8"))["failures"]
