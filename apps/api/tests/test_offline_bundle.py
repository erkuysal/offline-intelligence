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


ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_SPEC = ROOT / "config" / "delivery" / "offline-bundle-v1.example.json"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_spec(tmp_path: Path, *, checksum: str | None = None) -> Path:
    model = b"fake-gguf-model"
    (tmp_path / "model.gguf").write_bytes(model)
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    license_evidence = b"test-only license evidence\n"
    (tmp_path / "license.md").write_bytes(license_evidence)
    revision = "1" * 40
    source_report = {
        "schema_version": "1.0",
        "report_type": "release_source_preflight",
        "status": "passed",
        "source_root": "/clean/source",
        "source_revision": revision,
        "expected_revision": revision,
        "source_date_epoch": 1784758937,
        "git_tree_clean": True,
        "git_status_entries": [],
        "required_files": [],
        "forbidden_context_paths": [],
        "missing_dockerignore_patterns": [],
        "failures": [],
    }
    (tmp_path / "source-report.json").write_text(
        json.dumps(source_report), encoding="utf-8"
    )
    provenance = {
        "schema_version": "1.0",
        "spec_type": "release_artifact_provenance",
        "release_id": "offline-hub-0.4.0-test",
        "app_version": "0.4.0",
        "target_architecture": "linux-x86_64",
        "source_revision": revision,
        "source_report_path": "source-report.json",
        "artifacts": [
            {
                "artifact_type": "model",
                "artifact_id": "chat-model",
                "payload": {
                    "path": "model.gguf",
                    "bundle_path": "models/chat-model.gguf",
                    "sha256": digest(model),
                    "size_bytes": len(model),
                },
                "model_id": "test/model",
                "model_revision": "q4-test",
                "format": "GGUF",
                "license_evidence": {
                    "path": "license.md",
                    "bundle_path": "licenses/release-license-status.md",
                    "sha256": digest(license_evidence),
                    "size_bytes": len(license_evidence),
                },
            }
        ],
    }
    (tmp_path / "provenance-spec.json").write_text(
        json.dumps(provenance), encoding="utf-8"
    )
    payload = {
        "schema_version": "1.1",
        "spec_type": "offline_bundle_spec",
        "release_id": "offline-hub-0.4.0-test",
        "app_version": "0.4.0",
        "target_architecture": "linux-x86_64",
        "provenance": {
            "spec": "provenance-spec.json",
            "spec_path": "provenance/spec.json",
            "report_path": "provenance/report.json",
        },
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
                "source": "license.md",
                "path": "licenses/release-license-status.md",
                "artifact_type": "license",
                "version": "test",
                "origin": "test/license-review",
                "expected_sha256": digest(license_evidence),
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


def test_checked_in_example_uses_provenance_gated_schema() -> None:
    spec = BundleSpec.model_validate_json(EXAMPLE_SPEC.read_text(encoding="utf-8"))

    assert spec.schema_version == "1.1"
    assert spec.provenance.report_path == "provenance/report.json"


def test_builder_creates_deterministic_self_verifying_bundle(tmp_path: Path) -> None:
    spec = write_spec(tmp_path)
    first = tmp_path / "bundle-one"
    second = tmp_path / "bundle-two"

    first_manifest = build_offline_bundle(spec, first)
    second_manifest = build_offline_bundle(spec, second)

    assert first_manifest == second_manifest
    assert (first / "manifest.json").read_bytes() == (
        second / "manifest.json"
    ).read_bytes()
    assert (first / "checksums.sha256").read_bytes() == (
        second / "checksums.sha256"
    ).read_bytes()
    report = verify_offline_bundle(first)
    assert report.passed is True
    assert report.verified_file_count == 5
    assert first_manifest.source_revision == "1" * 40
    assert first_manifest.provenance_report_path == "provenance/report.json"


@pytest.mark.parametrize(
    "mutation", ["changed", "missing", "unexpected", "unexpected_directory"]
)
def test_verifier_fails_closed_on_bundle_tree_drift(
    tmp_path: Path, mutation: str
) -> None:
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


def test_verifier_rejects_symlinks_even_when_the_target_is_valid(
    tmp_path: Path,
) -> None:
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


def test_builder_rejects_mandatory_payload_without_provenance_coverage(
    tmp_path: Path,
) -> None:
    spec_path = write_spec(tmp_path)
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    (tmp_path / "extra.spdx.json").write_text("{}\n", encoding="utf-8")
    payload["inputs"].append(
        {
            "source": "extra.spdx.json",
            "path": "sbom/extra.spdx.json",
            "artifact_type": "sbom",
            "version": "test",
            "origin": "test",
            "contains_secrets": False,
        }
    )
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BundleError, match="coverage does not exactly match"):
        build_offline_bundle(spec_path, tmp_path / "bundle")


def test_verifier_rejects_semantically_mismatched_embedded_provenance(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    build_offline_bundle(write_spec(tmp_path), bundle)
    report_path = bundle / "provenance" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["app_version"] = "9.9.9"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report_sha256 = digest(report_path.read_bytes())

    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance_report_sha256"] = report_sha256
    for record in manifest["files"]:
        if record["path"] == "provenance/report.json":
            record["sha256"] = report_sha256
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksums = [
        f"{record['sha256']}  {record['path']}\n" for record in manifest["files"]
    ]
    checksums.append(f"{digest(manifest_path.read_bytes())}  manifest.json\n")
    (bundle / "checksums.sha256").write_text("".join(checksums), encoding="utf-8")

    verification = verify_offline_bundle(bundle)

    assert verification.passed is False
    assert (
        "embedded provenance app_version does not match manifest"
        in verification.failures
    )


@pytest.mark.parametrize(
    "path", ["../secret.env", "/absolute/file", "configs/prod.env"]
)
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
