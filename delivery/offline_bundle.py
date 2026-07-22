from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from delivery.release_provenance import (
    ExternalImageSpec,
    ModelSpec,
    ProjectImageSpec,
    ReleaseProvenanceReport,
    ReleaseProvenanceSpec,
    build_release_provenance_report,
    load_release_provenance_spec,
    write_release_provenance_report,
)


MANIFEST_NAME = "manifest.json"
CHECKSUMS_NAME = "checksums.sha256"
RESERVED_PATHS = {MANIFEST_NAME, CHECKSUMS_NAME}


class BundleError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BundleInput(StrictModel):
    source: str = Field(min_length=1)
    path: str = Field(min_length=1)
    artifact_type: Literal[
        "container_image",
        "model",
        "configuration",
        "migration",
        "application",
        "wheelhouse",
        "sbom",
        "license",
        "operator_tool",
        "documentation",
        "provenance",
    ]
    version: str = Field(min_length=1)
    origin: str = Field(min_length=1)
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    contains_secrets: Literal[False] = False

    @model_validator(mode="after")
    def validate_destination(self) -> Self:
        validate_bundle_path(self.path)
        return self


class BundleProvenance(StrictModel):
    spec: str = Field(min_length=1)
    spec_path: str = "provenance/spec.json"
    report_path: str = "provenance/report.json"

    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        validate_bundle_path(self.spec_path)
        validate_bundle_path(self.report_path)
        if self.spec_path == self.report_path:
            raise ValueError("provenance spec and report paths must differ")
        return self


class BundleSpec(StrictModel):
    schema_version: Literal["1.1"] = "1.1"
    spec_type: Literal["offline_bundle_spec"] = "offline_bundle_spec"
    release_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    app_version: str = Field(min_length=1)
    target_architecture: str = Field(min_length=1)
    provenance: BundleProvenance
    inputs: list[BundleInput] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_paths(self) -> Self:
        paths = [item.path for item in self.inputs]
        if len(paths) != len(set(paths)):
            raise ValueError("bundle input paths must be unique")
        generated_paths = {self.provenance.spec_path, self.provenance.report_path}
        collisions = sorted(set(paths) & generated_paths)
        if collisions:
            raise ValueError(
                f"bundle inputs collide with generated provenance: {collisions}"
            )
        return self


class BundleFile(StrictModel):
    path: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    version: str = Field(min_length=1)
    origin: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class BundleManifest(StrictModel):
    schema_version: Literal["1.1"] = "1.1"
    manifest_type: Literal["offline_release_bundle"] = "offline_release_bundle"
    release_id: str = Field(min_length=1)
    app_version: str = Field(min_length=1)
    target_architecture: str = Field(min_length=1)
    source_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    provenance_spec_path: str
    provenance_spec_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provenance_report_path: str
    provenance_report_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    files: list[BundleFile] = Field(min_length=1)
    total_size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def reject_duplicate_paths(self) -> Self:
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("bundle manifest paths must be unique")
        for path in paths:
            validate_bundle_path(path)
        validate_bundle_path(self.provenance_spec_path)
        validate_bundle_path(self.provenance_report_path)
        return self


class BundleVerification(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    report_type: Literal["offline_bundle_verification"] = "offline_bundle_verification"
    bundle: str
    release_id: str | None
    verified_file_count: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)
    failures: list[str]

    @property
    def passed(self) -> bool:
        return not self.failures


def validate_bundle_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(
            f"bundle path must be a normalized relative POSIX path: {value!r}"
        )
    if "\\" in value or value in RESERVED_PATHS:
        raise ValueError(f"bundle path is invalid or reserved: {value!r}")
    name = path.name.lower()
    if (name == ".env" or name.endswith(".env")) and not name.endswith(".example.env"):
        raise ValueError(f"secret-bearing environment files are not allowed: {value!r}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_bundle_spec(path: Path) -> BundleSpec:
    return BundleSpec.model_validate_json(path.read_text(encoding="utf-8"))


def load_bundle_manifest(path: Path) -> BundleManifest:
    return BundleManifest.model_validate_json(path.read_text(encoding="utf-8"))


def resolve_source(spec_path: Path, declared_source: str) -> Path:
    source = Path(declared_source).expanduser()
    if not source.is_absolute():
        source = spec_path.parent / source
    return source


def provenance_payload_types(
    provenance_spec: ReleaseProvenanceSpec,
) -> dict[str, str]:
    expected: dict[str, str] = {}
    for artifact in provenance_spec.artifacts:
        if isinstance(artifact, (ProjectImageSpec, ExternalImageSpec)):
            expected[artifact.archive.bundle_path] = "container_image"
            expected[artifact.sbom.bundle_path] = "sbom"
            if isinstance(artifact, ProjectImageSpec):
                for binding in artifact.native_bindings:
                    expected[binding.inventory.bundle_path] = "application"
        elif isinstance(artifact, ModelSpec):
            expected[artifact.payload.bundle_path] = "model"
            expected[artifact.license_evidence.bundle_path] = "license"
    return expected


def validate_provenance_gate(
    bundle_spec: BundleSpec,
    *,
    bundle_spec_path: Path,
) -> tuple[Path, ReleaseProvenanceReport, dict[str, BundleFile]]:
    provenance_spec_path = resolve_source(bundle_spec_path, bundle_spec.provenance.spec)
    if provenance_spec_path.is_symlink() or not provenance_spec_path.is_file():
        raise BundleError(
            "provenance specification must be a regular non-symlink file: "
            f"{provenance_spec_path}"
        )
    provenance_spec_path = provenance_spec_path.resolve()
    provenance_spec = load_release_provenance_spec(provenance_spec_path)
    report = build_release_provenance_report(
        provenance_spec,
        spec_path=provenance_spec_path,
    )
    if not report.passed:
        detail = "; ".join(report.failures[:5])
        raise BundleError(f"release provenance verification failed: {detail}")
    metadata = (
        ("release_id", bundle_spec.release_id, report.release_id),
        ("app_version", bundle_spec.app_version, report.app_version),
        (
            "target_architecture",
            bundle_spec.target_architecture,
            report.target_architecture,
        ),
    )
    for label, bundle_value, provenance_value in metadata:
        if bundle_value != provenance_value:
            raise BundleError(
                f"bundle/provenance {label} mismatch: "
                f"{bundle_value!r} != {provenance_value!r}"
            )

    inputs = {item.path: item for item in bundle_spec.inputs}
    expected_types = provenance_payload_types(provenance_spec)
    mandatory_paths = {
        item.path
        for item in bundle_spec.inputs
        if item.artifact_type in {"container_image", "model", "sbom"}
    }
    covered_mandatory_paths = {
        path
        for path, artifact_type in expected_types.items()
        if artifact_type in {"container_image", "model", "sbom"}
    }
    if mandatory_paths != covered_mandatory_paths:
        missing = sorted(mandatory_paths - covered_mandatory_paths)
        unexpected = sorted(covered_mandatory_paths - mandatory_paths)
        raise BundleError(
            "provenance coverage does not exactly match mandatory bundle payloads: "
            f"missing={missing}, unexpected={unexpected}"
        )
    for path, expected_type in expected_types.items():
        item = inputs.get(path)
        if item is None:
            raise BundleError(
                f"provenance payload is absent from bundle inputs: {path}"
            )
        if item.artifact_type != expected_type:
            raise BundleError(
                f"provenance payload type mismatch for {path}: "
                f"expected {expected_type}, found {item.artifact_type}"
            )

    records = {
        payload.bundle_path: BundleFile(
            path=payload.bundle_path,
            artifact_type=expected_types[payload.bundle_path],
            version="provenance-observed",
            origin="release-provenance-verifier",
            size_bytes=payload.size_bytes,
            sha256=payload.sha256,
        )
        for artifact in report.artifacts
        for payload in artifact.payloads
    }
    if set(records) != set(expected_types):
        raise BundleError("provenance report payload inventory is incomplete")
    return provenance_spec_path, report, records


def build_offline_bundle(spec_path: Path, output: Path) -> BundleManifest:
    spec_path = spec_path.resolve()
    spec = load_bundle_spec(spec_path)
    provenance_spec_path, provenance_report, provenance_records = (
        validate_provenance_gate(
            spec,
            bundle_spec_path=spec_path,
        )
    )
    output = output.resolve()
    if output.exists():
        raise BundleError(f"bundle output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        records: list[BundleFile] = []
        for item in sorted(spec.inputs, key=lambda candidate: candidate.path):
            source = resolve_source(spec_path, item.source)
            if source.is_symlink() or not source.is_file():
                raise BundleError(
                    f"bundle input must be a regular non-symlink file: {source}"
                )
            digest = sha256_file(source)
            if item.expected_sha256 is not None and not hmac.compare_digest(
                item.expected_sha256, digest
            ):
                raise BundleError(
                    f"bundle input checksum mismatch for {item.path}: "
                    f"expected {item.expected_sha256}, found {digest}"
                )
            provenance_record = provenance_records.get(item.path)
            if provenance_record is not None and (
                provenance_record.sha256 != digest
                or provenance_record.size_bytes != source.stat().st_size
            ):
                raise BundleError(
                    f"bundle payload identity differs from provenance for {item.path}"
                )
            destination = staging.joinpath(*PurePosixPath(item.path).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            records.append(
                BundleFile(
                    path=item.path,
                    artifact_type=item.artifact_type,
                    version=item.version,
                    origin=item.origin,
                    size_bytes=destination.stat().st_size,
                    sha256=digest,
                )
            )

        generated = (
            (
                spec.provenance.spec_path,
                provenance_spec_path,
                "release-provenance-spec",
            ),
            (
                spec.provenance.report_path,
                None,
                "release-provenance-report",
            ),
        )
        for bundle_path, source_path, origin in generated:
            destination = staging.joinpath(*PurePosixPath(bundle_path).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source_path is None:
                write_release_provenance_report(provenance_report, destination)
            else:
                shutil.copyfile(source_path, destination)
            records.append(
                BundleFile(
                    path=bundle_path,
                    artifact_type="provenance",
                    version="1.0",
                    origin=origin,
                    size_bytes=destination.stat().st_size,
                    sha256=sha256_file(destination),
                )
            )
        records.sort(key=lambda record: record.path)
        provenance_spec_record = next(
            record for record in records if record.path == spec.provenance.spec_path
        )
        provenance_report_record = next(
            record for record in records if record.path == spec.provenance.report_path
        )
        manifest = BundleManifest(
            release_id=spec.release_id,
            app_version=spec.app_version,
            target_architecture=spec.target_architecture,
            source_revision=provenance_report.source_revision,
            provenance_spec_path=spec.provenance.spec_path,
            provenance_spec_sha256=provenance_spec_record.sha256,
            provenance_report_path=spec.provenance.report_path,
            provenance_report_sha256=provenance_report_record.sha256,
            files=records,
            total_size_bytes=sum(record.size_bytes for record in records),
        )
        manifest_path = staging / MANIFEST_NAME
        manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
        checksum_records = [(record.sha256, record.path) for record in records] + [
            (sha256_file(manifest_path), MANIFEST_NAME)
        ]
        (staging / CHECKSUMS_NAME).write_text(
            "".join(f"{digest}  {path}\n" for digest, path in checksum_records),
            encoding="utf-8",
        )
        os.replace(staging, output)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def verify_offline_bundle(bundle: Path) -> BundleVerification:
    bundle = bundle.expanduser().absolute()
    failures: list[str] = []
    manifest: BundleManifest | None = None
    manifest_path = bundle / MANIFEST_NAME
    checksums_path = bundle / CHECKSUMS_NAME
    try:
        if bundle.is_symlink() or not bundle.is_dir():
            raise BundleError(f"bundle is not a regular directory: {bundle}")
        if manifest_path.is_symlink():
            raise BundleError("manifest.json must not be a symlink")
        manifest = load_bundle_manifest(manifest_path)
    except (OSError, ValueError) as exc:
        failures.append(f"manifest: {exc}")
        return verification_result(bundle, manifest, failures)

    expected_paths = {record.path for record in manifest.files} | RESERVED_PATHS
    expected_directories = {
        parent.as_posix()
        for record in manifest.files
        for parent in PurePosixPath(record.path).parents
        if parent.as_posix() != "."
    }
    actual_paths: set[str] = set()
    actual_directories: set[str] = set()
    for path in bundle.rglob("*"):
        if path.is_file() or path.is_symlink():
            relative = path.relative_to(bundle).as_posix()
            actual_paths.add(relative)
            if path.is_symlink():
                failures.append(f"symlink is not allowed: {relative}")
        elif path.is_dir():
            actual_directories.add(path.relative_to(bundle).as_posix())
    missing = sorted(expected_paths - actual_paths)
    unexpected = sorted(actual_paths - expected_paths)
    failures.extend(f"missing file: {path}" for path in missing)
    failures.extend(f"unexpected file: {path}" for path in unexpected)
    failures.extend(
        f"unexpected directory: {path}"
        for path in sorted(actual_directories - expected_directories)
    )

    for record in manifest.files:
        path = bundle.joinpath(*PurePosixPath(record.path).parts)
        if not path.exists() or path.is_symlink() or not path.is_file():
            continue
        size = path.stat().st_size
        if size != record.size_bytes:
            failures.append(
                f"size mismatch for {record.path}: expected {record.size_bytes}, found {size}"
            )
        digest = sha256_file(path)
        if not hmac.compare_digest(record.sha256, digest):
            failures.append(
                f"checksum mismatch for {record.path}: expected {record.sha256}, found {digest}"
            )

    records_by_path = {record.path: record for record in manifest.files}
    provenance_spec_record = records_by_path.get(manifest.provenance_spec_path)
    provenance_report_record = records_by_path.get(manifest.provenance_report_path)
    if (
        provenance_spec_record is None
        or provenance_spec_record.sha256 != manifest.provenance_spec_sha256
    ):
        failures.append("manifest provenance specification identity is inconsistent")
    if (
        provenance_report_record is None
        or provenance_report_record.sha256 != manifest.provenance_report_sha256
    ):
        failures.append("manifest provenance report identity is inconsistent")
    try:
        provenance_report_path = bundle.joinpath(
            *PurePosixPath(manifest.provenance_report_path).parts
        )
        if provenance_report_path.is_symlink() or not provenance_report_path.is_file():
            raise BundleError("provenance report must be a regular non-symlink file")
        provenance_report = ReleaseProvenanceReport.model_validate_json(
            provenance_report_path.read_text(encoding="utf-8")
        )
        if not provenance_report.passed:
            failures.append("embedded provenance report did not pass")
        if provenance_report.release_id != manifest.release_id:
            failures.append("embedded provenance release_id does not match manifest")
        if provenance_report.app_version != manifest.app_version:
            failures.append("embedded provenance app_version does not match manifest")
        if provenance_report.target_architecture != manifest.target_architecture:
            failures.append("embedded provenance architecture does not match manifest")
        if provenance_report.source_revision != manifest.source_revision:
            failures.append(
                "embedded provenance source revision does not match manifest"
            )
        if provenance_report.provenance_spec_sha256 != manifest.provenance_spec_sha256:
            failures.append(
                "embedded provenance specification digest does not match manifest"
            )
        reported_paths = {
            payload.bundle_path
            for artifact in provenance_report.artifacts
            for payload in artifact.payloads
        }
        mandatory_manifest_paths = {
            record.path
            for record in manifest.files
            if record.artifact_type in {"container_image", "model", "sbom"}
        }
        failures.extend(
            f"mandatory manifest payload lacks provenance: {path}"
            for path in sorted(mandatory_manifest_paths - reported_paths)
        )
        for artifact in provenance_report.artifacts:
            for payload in artifact.payloads:
                payload_record = records_by_path.get(payload.bundle_path)
                if payload_record is None:
                    failures.append(
                        f"provenance payload is missing from manifest: {payload.bundle_path}"
                    )
                elif (
                    payload_record.sha256 != payload.sha256
                    or payload_record.size_bytes != payload.size_bytes
                ):
                    failures.append(
                        f"provenance payload identity does not match manifest: "
                        f"{payload.bundle_path}"
                    )
    except (OSError, ValueError) as exc:
        failures.append(f"provenance report: {exc}")

    expected_checksums = {record.path: record.sha256 for record in manifest.files} | {
        MANIFEST_NAME: sha256_file(manifest_path)
    }
    try:
        if checksums_path.is_symlink():
            raise BundleError("checksums.sha256 must not be a symlink")
        actual_checksums = parse_checksum_inventory(checksums_path)
        if actual_checksums != expected_checksums:
            failures.append("checksum inventory does not exactly match the manifest")
    except (OSError, ValueError) as exc:
        failures.append(f"checksum inventory: {exc}")

    if manifest.total_size_bytes != sum(record.size_bytes for record in manifest.files):
        failures.append("manifest total_size_bytes does not match its file records")
    return verification_result(bundle, manifest, failures)


def parse_checksum_inventory(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if len(line) < 67 or line[64:66] != "  ":
            raise BundleError(f"invalid checksum line {line_number}")
        digest, name = line[:64], line[66:]
        if (
            not name
            or name in records
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise BundleError(f"invalid checksum line {line_number}")
        if name not in RESERVED_PATHS:
            validate_bundle_path(name)
        records[name] = digest
    return records


def verification_result(
    bundle: Path,
    manifest: BundleManifest | None,
    failures: list[str],
) -> BundleVerification:
    return BundleVerification(
        bundle=str(bundle),
        release_id=manifest.release_id if manifest is not None else None,
        verified_file_count=len(manifest.files) if manifest is not None else 0,
        total_size_bytes=manifest.total_size_bytes if manifest is not None else 0,
        failures=failures,
    )


def canonical_json(model: BaseModel) -> str:
    return (
        json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def format_verification_summary(report: BundleVerification) -> str:
    status = "PASSED" if report.passed else "FAILED"
    lines = [
        f"Offline bundle verification: {status}",
        f"Bundle: {report.bundle}",
        f"Release: {report.release_id or 'unknown'}",
        f"Files: {report.verified_file_count}",
        f"Payload bytes: {report.total_size_bytes}",
    ]
    lines.extend(f"Failure: {failure}" for failure in report.failures)
    return "\n".join(lines)
