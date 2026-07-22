from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

import manage
from delivery.release_provenance import (
    ReleaseProvenanceSpec,
    build_release_provenance_report,
    inspect_spdx,
)
from delivery.release_source import ReleaseSourceReport, RequiredFileRecord


REVISION = "1" * 40
SOURCE_DATE_EPOCH = 1784757083
IMAGE_INDEX = "2" * 64
SUBJECT_MANIFEST = "3" * 64
NATIVE_BINARY = "4" * 64
ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_SPEC = ROOT / "config" / "supply-chain" / "release-provenance-v1.example.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload(path: Path, bundle_path: str) -> dict[str, object]:
    return {
        "path": path.name,
        "bundle_path": bundle_path,
        "sha256": digest(path),
        "size_bytes": path.stat().st_size,
    }


def add_tar_bytes(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mtime = 0
    archive.addfile(info, io.BytesIO(content))


def write_image_archive(
    path: Path,
    *,
    revision: str = REVISION,
    source_date_epoch: int = SOURCE_DATE_EPOCH,
) -> str:
    config = json.dumps(
        {
            "config": {
                "Labels": {
                    "org.opencontainers.image.revision": revision,
                    "org.offline-intelligence-hub.source-date-epoch": str(source_date_epoch),
                }
            }
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    config_digest = hashlib.sha256(config).hexdigest()
    config_path = f"blobs/sha256/{config_digest}"
    manifest = json.dumps(
        [
            {
                "Config": config_path,
                "RepoTags": ["example/api:1.0", "example/worker:1.0"],
                "Layers": [],
            }
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    with tarfile.open(path, "w") as archive:
        add_tar_bytes(archive, config_path, config)
        add_tar_bytes(archive, "manifest.json", manifest)
    return config_digest


def spdx_payload(*, namespace: str = "first", subject_digest: str = SUBJECT_MANIFEST) -> dict:
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "example-api",
        "documentNamespace": f"https://example.invalid/{namespace}",
        "creationInfo": {"created": "2026-07-23T00:00:00Z", "creators": ["Tool: test"]},
        "packages": [
            {
                "name": "example-api",
                "SPDXID": "SPDXRef-Image",
                "versionInfo": "1.0",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "supplier": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": (
                            "pkg:oci/example-api@sha256%3A"
                            f"{subject_digest}?arch=amd64&tag=1.0"
                        ),
                    }
                ],
                "primaryPackagePurpose": "CONTAINER",
            },
            {
                "name": "dependency",
                "SPDXID": "SPDXRef-Package-dependency",
                "versionInfo": "2.0",
                "supplier": "Organization: Example",
                "downloadLocation": "NOASSERTION",
                "licenseConcluded": "MIT",
                "licenseDeclared": "MIT",
                "externalRefs": [],
            },
        ],
        "relationships": [],
    }


def write_provenance_fixture(tmp_path: Path) -> tuple[Path, ReleaseProvenanceSpec]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    source_report = ReleaseSourceReport(
        status="passed",
        source_root="/clean/source",
        source_revision=REVISION,
        expected_revision=REVISION,
        source_date_epoch=SOURCE_DATE_EPOCH,
        git_tree_clean=True,
        git_status_entries=[],
        required_files=[
            RequiredFileRecord(
                path="Dockerfile",
                sha256=digest(dockerfile),
                size_bytes=dockerfile.stat().st_size,
            )
        ],
        forbidden_context_paths=[],
        missing_dockerignore_patterns=[],
        failures=[],
    )
    source_report_path = tmp_path / "source-report.json"
    source_report_path.write_text(source_report.model_dump_json(indent=2), encoding="utf-8")

    archive = tmp_path / "application.tar"
    config_digest = write_image_archive(archive)
    sbom = tmp_path / "application.spdx.json"
    sbom.write_text(json.dumps(spdx_payload()), encoding="utf-8")
    native_inventory = tmp_path / "native.json"
    native_inventory.write_text(
        json.dumps(
            {
                "binary": {"sha256": NATIVE_BINARY},
                "application_image": {"image_id": f"sha256:{IMAGE_INDEX}"},
                "sbom": {"sha256": digest(sbom)},
            }
        ),
        encoding="utf-8",
    )
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF-test-model")
    license_evidence = tmp_path / "license.md"
    license_evidence.write_text("internal test evidence\n", encoding="utf-8")

    spec_payload = {
        "schema_version": "1.0",
        "spec_type": "release_artifact_provenance",
        "release_id": "offline-hub-1.0-test",
        "app_version": "1.0",
        "target_architecture": "linux-x86_64",
        "source_revision": REVISION,
        "source_report_path": source_report_path.name,
        "artifacts": [
            {
                "artifact_type": "project_container_image",
                "artifact_id": "application",
                "archive": payload(archive, "images/application.tar"),
                "repo_tags": ["example/api:1.0", "example/worker:1.0"],
                "image_index_sha256": IMAGE_INDEX,
                "image_config_sha256": config_digest,
                "dockerfile_path": "Dockerfile",
                "dockerfile_sha256": digest(dockerfile),
                "sbom": {
                    **payload(sbom, "sbom/application.spdx.json"),
                    "format": "SPDX-2.3",
                    "package_count": 2,
                    "subject_name": "example-api",
                    "subject_manifest_sha256": SUBJECT_MANIFEST,
                },
                "native_bindings": [
                    {
                        "component": "vector-similarity",
                        "inventory": payload(native_inventory, "inventory/native.json"),
                        "binary_sha256": NATIVE_BINARY,
                    }
                ],
            },
            {
                "artifact_type": "model",
                "artifact_id": "chat-model",
                "payload": payload(model, "models/chat-model.gguf"),
                "model_id": "example/chat-model",
                "model_revision": "revision-1",
                "format": "GGUF",
                "license_evidence_path": license_evidence.name,
            },
        ],
    }
    spec_path = tmp_path / "provenance-spec.json"
    spec_path.write_text(json.dumps(spec_payload), encoding="utf-8")
    return spec_path, ReleaseProvenanceSpec.model_validate(spec_payload)


def test_provenance_binds_source_image_sbom_native_and_model(tmp_path: Path) -> None:
    spec_path, spec = write_provenance_fixture(tmp_path)

    report = build_release_provenance_report(spec, spec_path=spec_path)

    assert report.passed is True
    assert report.source_revision == REVISION
    assert report.source_date_epoch == SOURCE_DATE_EPOCH
    application = report.artifacts[0]
    assert application.identities["image_index_sha256"] == IMAGE_INDEX
    assert application.identities["sbom_subject_manifest_sha256"] == SUBJECT_MANIFEST
    assert application.identities["sbom_component_count"] == 1
    assert application.identities["native_binary_sha256"] == {
        "vector-similarity": NATIVE_BINARY
    }


def test_checked_in_example_spec_is_strictly_valid() -> None:
    spec = ReleaseProvenanceSpec.model_validate_json(EXAMPLE_SPEC.read_text(encoding="utf-8"))

    assert spec.artifacts[0].artifact_id == "application"


def test_external_image_binds_upstream_archive_and_sbom_without_source_labels(
    tmp_path: Path,
) -> None:
    spec_path, spec = write_provenance_fixture(tmp_path)
    payload_value = spec.model_dump(mode="json")
    image = payload_value["artifacts"][0]
    image["artifact_type"] = "external_container_image"
    image["artifact_id"] = "external-runtime"
    image["upstream_reference"] = "registry.example/runtime@sha256:" + IMAGE_INDEX
    for key in ("dockerfile_path", "dockerfile_sha256", "native_bindings"):
        image.pop(key)
    payload_value["artifacts"] = [image]
    external_spec = ReleaseProvenanceSpec.model_validate(payload_value)

    report = build_release_provenance_report(external_spec, spec_path=spec_path)

    assert report.passed is True
    assert report.artifacts[0].identities["upstream_reference"].startswith(
        "registry.example/runtime@sha256:"
    )


def test_image_source_label_mismatch_fails_closed(tmp_path: Path) -> None:
    spec_path, spec = write_provenance_fixture(tmp_path)
    archive = tmp_path / "application.tar"
    config_digest = write_image_archive(archive, revision="9" * 40)
    spec.artifacts[0].archive.sha256 = digest(archive)  # type: ignore[union-attr]
    spec.artifacts[0].archive.size_bytes = archive.stat().st_size  # type: ignore[union-attr]
    spec.artifacts[0].image_config_sha256 = config_digest  # type: ignore[union-attr]

    report = build_release_provenance_report(spec, spec_path=spec_path)

    assert report.passed is False
    assert any("source label mismatch" in failure for failure in report.failures)


def test_payload_checksum_mismatch_fails_closed(tmp_path: Path) -> None:
    spec_path, spec = write_provenance_fixture(tmp_path)
    (tmp_path / "model.gguf").write_bytes(b"changed")

    report = build_release_provenance_report(spec, spec_path=spec_path)

    assert report.passed is False
    assert any("chat-model model checksum mismatch" in failure for failure in report.failures)


def test_sbom_subject_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    spec_path, spec = write_provenance_fixture(tmp_path)
    sbom = tmp_path / "application.spdx.json"
    sbom.write_text(json.dumps(spdx_payload(subject_digest="8" * 64)), encoding="utf-8")
    image = spec.artifacts[0]
    image.sbom.sha256 = digest(sbom)  # type: ignore[union-attr]
    native = tmp_path / "native.json"
    native_payload = json.loads(native.read_text(encoding="utf-8"))
    native_payload["sbom"]["sha256"] = digest(sbom)
    native.write_text(json.dumps(native_payload), encoding="utf-8")
    image.native_bindings[0].inventory.sha256 = digest(native)  # type: ignore[union-attr]
    image.native_bindings[0].inventory.size_bytes = native.stat().st_size  # type: ignore[union-attr]

    report = build_release_provenance_report(spec, spec_path=spec_path)

    assert report.passed is False
    assert any("SBOM subject manifest mismatch" in failure for failure in report.failures)


def test_native_inventory_image_mismatch_fails_closed(tmp_path: Path) -> None:
    spec_path, spec = write_provenance_fixture(tmp_path)
    native = tmp_path / "native.json"
    native_payload = json.loads(native.read_text(encoding="utf-8"))
    native_payload["application_image"]["image_id"] = f"sha256:{'7' * 64}"
    native.write_text(json.dumps(native_payload), encoding="utf-8")
    image = spec.artifacts[0]
    image.native_bindings[0].inventory.sha256 = digest(native)  # type: ignore[union-attr]
    image.native_bindings[0].inventory.size_bytes = native.stat().st_size  # type: ignore[union-attr]

    report = build_release_provenance_report(spec, spec_path=spec_path)

    assert report.passed is False
    assert any("native inventory image mismatch" in failure for failure in report.failures)


def test_normalized_spdx_inventory_ignores_volatile_document_metadata(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps(spdx_payload(namespace="first")), encoding="utf-8")
    second_payload = spdx_payload(namespace="second")
    second_payload["creationInfo"]["created"] = "2027-01-01T00:00:00Z"
    second.write_text(json.dumps(second_payload), encoding="utf-8")
    _, spec = write_provenance_fixture(tmp_path / "fixture")
    sbom_spec = spec.artifacts[0].sbom  # type: ignore[union-attr]

    first_identity = inspect_spdx(first, sbom_spec)
    second_identity = inspect_spdx(second, sbom_spec)

    assert first_identity == second_identity


def test_cli_writes_machine_readable_failure_report(tmp_path: Path) -> None:
    spec_path, _spec = write_provenance_fixture(tmp_path)
    (tmp_path / "model.gguf").unlink()
    output = tmp_path / "report.json"

    status = manage.release_provenance_verify(
        argparse.Namespace(spec=str(spec_path), output=str(output))
    )

    assert status == 1
    payload_value = json.loads(output.read_text(encoding="utf-8"))
    assert payload_value["status"] == "failed"
    assert any("chat-model model" in failure for failure in payload_value["failures"])
