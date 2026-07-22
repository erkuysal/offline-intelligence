from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
from typing import Annotated, Any, Literal, Self
from urllib.parse import unquote

from pydantic import BaseModel, ConfigDict, Field, model_validator

from delivery.release_source import (
    ReleaseSourceReport,
    sha256_file,
    validate_relative_path,
)


SHA256_PATTERN = r"^[a-f0-9]{64}$"
REVISION_PATTERN = r"^[a-f0-9]{40}$"
OCI_PURL_DIGEST = re.compile(r"@sha256:([a-f0-9]{64})(?:\?|$)")


class ReleaseProvenanceError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PayloadSpec(StrictModel):
    path: str
    bundle_path: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        validate_relative_path(self.path)
        validate_relative_path(self.bundle_path)
        return self


class SpdxSpec(PayloadSpec):
    format: Literal["SPDX-2.3"] = "SPDX-2.3"
    package_count: int = Field(ge=1)
    subject_name: str = Field(min_length=1)
    subject_manifest_sha256: str = Field(pattern=SHA256_PATTERN)


class NativeBinding(StrictModel):
    component: str = Field(min_length=1)
    inventory: PayloadSpec
    binary_sha256: str = Field(pattern=SHA256_PATTERN)


class ProjectImageSpec(StrictModel):
    artifact_type: Literal["project_container_image"] = "project_container_image"
    artifact_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    archive: PayloadSpec
    repo_tags: list[str] = Field(min_length=1)
    image_index_sha256: str = Field(pattern=SHA256_PATTERN)
    image_config_sha256: str = Field(pattern=SHA256_PATTERN)
    dockerfile_path: str
    dockerfile_sha256: str = Field(pattern=SHA256_PATTERN)
    sbom: SpdxSpec
    native_bindings: list[NativeBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_image(self) -> Self:
        validate_relative_path(self.dockerfile_path)
        if len(self.repo_tags) != len(set(self.repo_tags)):
            raise ValueError("image repository tags must be unique")
        components = [binding.component for binding in self.native_bindings]
        if len(components) != len(set(components)):
            raise ValueError("native component names must be unique")
        return self


class ExternalImageSpec(StrictModel):
    artifact_type: Literal["external_container_image"] = "external_container_image"
    artifact_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    archive: PayloadSpec
    repo_tags: list[str] = Field(min_length=1)
    image_index_sha256: str = Field(pattern=SHA256_PATTERN)
    image_config_sha256: str = Field(pattern=SHA256_PATTERN)
    upstream_reference: str = Field(min_length=1)
    sbom: SpdxSpec

    @model_validator(mode="after")
    def validate_image(self) -> Self:
        if len(self.repo_tags) != len(set(self.repo_tags)):
            raise ValueError("image repository tags must be unique")
        return self


class ModelSpec(StrictModel):
    artifact_type: Literal["model"] = "model"
    artifact_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    payload: PayloadSpec
    model_id: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    format: Literal["GGUF"] = "GGUF"
    license_evidence: PayloadSpec


ArtifactSpec = Annotated[
    ProjectImageSpec | ExternalImageSpec | ModelSpec,
    Field(discriminator="artifact_type"),
]


class ReleaseProvenanceSpec(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    spec_type: Literal["release_artifact_provenance"] = "release_artifact_provenance"
    release_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    app_version: str = Field(min_length=1)
    target_architecture: str = Field(min_length=1)
    source_revision: str = Field(pattern=REVISION_PATTERN)
    source_report_path: str
    artifacts: list[ArtifactSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_spec(self) -> Self:
        validate_relative_path(self.source_report_path)
        artifact_ids = [artifact.artifact_id for artifact in self.artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("artifact IDs must be unique")
        payloads: list[PayloadSpec] = []
        for artifact in self.artifacts:
            if isinstance(artifact, (ProjectImageSpec, ExternalImageSpec)):
                payloads.extend([artifact.archive, artifact.sbom])
                if isinstance(artifact, ProjectImageSpec):
                    payloads.extend(
                        binding.inventory for binding in artifact.native_bindings
                    )
            else:
                payloads.extend([artifact.payload, artifact.license_evidence])
        identities: dict[str, tuple[str, int]] = {}
        for payload in payloads:
            identity = (payload.sha256, payload.size_bytes)
            previous = identities.setdefault(payload.bundle_path, identity)
            if previous != identity:
                raise ValueError(
                    "shared artifact bundle paths must declare the same payload identity"
                )
        return self


class PayloadRecord(StrictModel):
    bundle_path: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(ge=0)


class ArtifactRecord(StrictModel):
    artifact_id: str
    artifact_type: Literal[
        "project_container_image", "external_container_image", "model"
    ]
    payloads: list[PayloadRecord]
    identities: dict[str, Any]


class ReleaseProvenanceReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    report_type: Literal["release_artifact_provenance"] = "release_artifact_provenance"
    status: Literal["passed", "failed"]
    release_id: str
    app_version: str
    target_architecture: str
    source_revision: str
    source_date_epoch: int | None
    source_report_sha256: str | None
    provenance_spec_sha256: str
    artifacts: list[ArtifactRecord]
    failures: list[str]

    @property
    def passed(self) -> bool:
        return not self.failures


def canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_evidence_path(spec_path: Path, declared_path: str) -> Path:
    validate_relative_path(declared_path)
    return spec_path.parent.resolve().joinpath(*PurePosixPath(declared_path).parts)


def evidence_path_has_symlink(spec_path: Path, path: Path) -> bool:
    root = spec_path.parent.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def load_release_provenance_spec(path: Path) -> ReleaseProvenanceSpec:
    return ReleaseProvenanceSpec.model_validate_json(path.read_text(encoding="utf-8"))


def verify_payload(
    spec_path: Path,
    payload: PayloadSpec,
    *,
    label: str,
    failures: list[str],
) -> tuple[Path, PayloadRecord | None]:
    path = resolve_evidence_path(spec_path, payload.path)
    if evidence_path_has_symlink(spec_path, path) or not path.is_file():
        failures.append(f"{label} is missing or not a regular file: {payload.path}")
        return path, None
    size = path.stat().st_size
    digest = sha256_file(path)
    if size != payload.size_bytes:
        failures.append(
            f"{label} size mismatch: expected {payload.size_bytes}, found {size}"
        )
    if digest != payload.sha256:
        failures.append(
            f"{label} checksum mismatch: expected {payload.sha256}, found {digest}"
        )
    return path, PayloadRecord(
        bundle_path=payload.bundle_path,
        sha256=digest,
        size_bytes=size,
    )


def read_json_tar_member(archive: tarfile.TarFile, name: str) -> object:
    try:
        member = archive.getmember(name)
    except KeyError as exc:
        raise ReleaseProvenanceError(f"image archive is missing {name}") from exc
    if not member.isfile() or member.issym() or member.islnk():
        raise ReleaseProvenanceError(
            f"image archive member must be a regular file: {name}"
        )
    handle = archive.extractfile(member)
    if handle is None:
        raise ReleaseProvenanceError(f"image archive member cannot be read: {name}")
    try:
        return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ReleaseProvenanceError(
            f"image archive member is invalid JSON: {name}"
        ) from exc


def inspect_image_archive(
    path: Path,
    image: ProjectImageSpec | ExternalImageSpec,
) -> tuple[str, dict[str, str]]:
    try:
        with tarfile.open(path, mode="r:*") as archive:
            manifest = read_json_tar_member(archive, "manifest.json")
            if not isinstance(manifest, list) or len(manifest) != 1:
                raise ReleaseProvenanceError(
                    "image archive must contain exactly one image manifest"
                )
            entry = manifest[0]
            if not isinstance(entry, dict):
                raise ReleaseProvenanceError(
                    "image archive manifest entry must be an object"
                )
            repo_tags = entry.get("RepoTags")
            if not isinstance(repo_tags, list) or set(repo_tags) != set(
                image.repo_tags
            ):
                raise ReleaseProvenanceError(
                    f"image archive tags mismatch: expected {sorted(image.repo_tags)}, "
                    f"found {repo_tags!r}"
                )
            config_path = entry.get("Config")
            if not isinstance(config_path, str):
                raise ReleaseProvenanceError(
                    "image archive manifest has no config path"
                )
            config_name = PurePosixPath(config_path).name
            if not re.fullmatch(
                SHA256_PATTERN.removeprefix("^").removesuffix("$"), config_name
            ):
                raise ReleaseProvenanceError(
                    "image archive config path is not SHA-256 addressed"
                )
            config = read_json_tar_member(archive, config_path)
            if not isinstance(config, dict):
                raise ReleaseProvenanceError("image archive config must be an object")
            config_member = archive.getmember(config_path)
            config_handle = archive.extractfile(config_member)
            if config_handle is None:
                raise ReleaseProvenanceError("image archive config cannot be read")
            config_digest = hashlib.sha256(config_handle.read()).hexdigest()
            if config_digest != config_name:
                raise ReleaseProvenanceError(
                    f"image config content mismatch: expected {config_name}, found {config_digest}"
                )
            labels_value = config.get("config", {}).get("Labels", {})
            if labels_value is None:
                labels_value = {}
            if not isinstance(labels_value, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in labels_value.items()
            ):
                raise ReleaseProvenanceError("image config labels must be strings")
            return config_digest, labels_value
    except (OSError, tarfile.TarError) as exc:
        raise ReleaseProvenanceError(f"cannot inspect image archive: {exc}") from exc


def normalized_spdx_packages(packages: list[object]) -> tuple[int, str]:
    normalized: list[dict[str, object]] = []
    for package in packages:
        if not isinstance(package, dict):
            raise ReleaseProvenanceError("SPDX package entries must be objects")
        if package.get("primaryPackagePurpose") == "CONTAINER":
            continue
        normalized.append(
            {
                key: package.get(key)
                for key in (
                    "name",
                    "versionInfo",
                    "supplier",
                    "downloadLocation",
                    "licenseConcluded",
                    "licenseDeclared",
                    "externalRefs",
                )
            }
        )
    normalized.sort(
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"))
    )
    return len(normalized), canonical_json_sha256(normalized)


def inspect_spdx(path: Path, sbom: SpdxSpec) -> tuple[str, int, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseProvenanceError(f"cannot read SPDX document: {exc}") from exc
    if not isinstance(document, dict) or document.get("spdxVersion") != sbom.format:
        raise ReleaseProvenanceError(f"SBOM must be {sbom.format}")
    packages = document.get("packages")
    if not isinstance(packages, list) or len(packages) != sbom.package_count:
        found = len(packages) if isinstance(packages, list) else "invalid"
        raise ReleaseProvenanceError(
            f"SBOM package count mismatch: expected {sbom.package_count}, found {found}"
        )
    subjects = [
        package
        for package in packages
        if isinstance(package, dict) and package.get("name") == sbom.subject_name
    ]
    if len(subjects) != 1:
        raise ReleaseProvenanceError(
            "SBOM must contain exactly one named image subject"
        )
    subject = subjects[0]
    references = subject.get("externalRefs")
    digests: set[str] = set()
    if isinstance(references, list):
        for reference in references:
            if (
                not isinstance(reference, dict)
                or reference.get("referenceType") != "purl"
            ):
                continue
            locator = reference.get("referenceLocator")
            if not isinstance(locator, str):
                continue
            match = OCI_PURL_DIGEST.search(unquote(locator))
            if match:
                digests.add(match.group(1))
    if digests != {sbom.subject_manifest_sha256}:
        raise ReleaseProvenanceError(
            "SBOM subject manifest mismatch: "
            f"expected {sbom.subject_manifest_sha256}, found {sorted(digests)}"
        )
    component_count, inventory_digest = normalized_spdx_packages(packages)
    return sbom.subject_manifest_sha256, component_count, inventory_digest


def validate_native_binding(
    path: Path,
    binding: NativeBinding,
    image: ProjectImageSpec,
) -> None:
    try:
        inventory = json.loads(path.read_text(encoding="utf-8"))
        binary_sha256 = inventory["binary"]["sha256"]
        image_id = inventory["application_image"]["image_id"]
        sbom_sha256 = inventory["sbom"]["sha256"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ReleaseProvenanceError(
            f"native inventory for {binding.component} is invalid: {exc}"
        ) from exc
    if binary_sha256 != binding.binary_sha256:
        raise ReleaseProvenanceError(
            f"native binary mismatch for {binding.component}: expected "
            f"{binding.binary_sha256}, found {binary_sha256}"
        )
    if image_id != f"sha256:{image.image_index_sha256}":
        raise ReleaseProvenanceError(
            f"native inventory image mismatch for {binding.component}: found {image_id}"
        )
    if sbom_sha256 != image.sbom.sha256:
        raise ReleaseProvenanceError(
            f"native inventory SBOM mismatch for {binding.component}: found {sbom_sha256}"
        )


def build_release_provenance_report(
    spec: ReleaseProvenanceSpec,
    *,
    spec_path: Path,
) -> ReleaseProvenanceReport:
    spec_path = spec_path.expanduser().resolve()
    failures: list[str] = []
    artifacts: list[ArtifactRecord] = []
    source_report_path = resolve_evidence_path(spec_path, spec.source_report_path)
    source_report_sha256: str | None = None
    source_date_epoch: int | None = None
    source_files: dict[str, str] = {}
    try:
        if (
            evidence_path_has_symlink(spec_path, source_report_path)
            or not source_report_path.is_file()
        ):
            raise ReleaseProvenanceError(
                f"missing, symlinked, or not a regular file: {spec.source_report_path}"
            )
        source_report_sha256 = sha256_file(source_report_path)
        source_report = ReleaseSourceReport.model_validate_json(
            source_report_path.read_text(encoding="utf-8")
        )
        source_date_epoch = source_report.source_date_epoch
        source_files = {
            record.path: record.sha256 for record in source_report.required_files
        }
        if not source_report.passed:
            failures.append("source preflight report did not pass")
        if source_report.source_revision != spec.source_revision:
            failures.append(
                f"source report revision mismatch: expected {spec.source_revision}, "
                f"found {source_report.source_revision}"
            )
    except (OSError, ValueError) as exc:
        failures.append(f"source preflight report is invalid: {exc}")

    for artifact in spec.artifacts:
        artifact_failures: list[str] = []
        payloads: list[PayloadRecord] = []
        identities: dict[str, Any] = {}
        if isinstance(artifact, (ProjectImageSpec, ExternalImageSpec)):
            archive_path, archive_record = verify_payload(
                spec_path,
                artifact.archive,
                label=f"{artifact.artifact_id} image archive",
                failures=artifact_failures,
            )
            if archive_record:
                payloads.append(archive_record)
            if isinstance(artifact, ProjectImageSpec):
                expected_dockerfile = source_files.get(artifact.dockerfile_path)
                if expected_dockerfile != artifact.dockerfile_sha256:
                    artifact_failures.append(
                        f"{artifact.artifact_id} Dockerfile is not bound to the source report"
                    )
            if archive_path.is_file():
                try:
                    config_digest, labels = inspect_image_archive(
                        archive_path, artifact
                    )
                    if config_digest != artifact.image_config_sha256:
                        artifact_failures.append(
                            f"{artifact.artifact_id} image config mismatch: expected "
                            f"{artifact.image_config_sha256}, found {config_digest}"
                        )
                    identities.update(
                        {
                            "image_index_sha256": artifact.image_index_sha256,
                            "image_config_sha256": config_digest,
                            "repo_tags": sorted(artifact.repo_tags),
                        }
                    )
                    if isinstance(artifact, ProjectImageSpec):
                        revision = labels.get("org.opencontainers.image.revision")
                        epoch = labels.get(
                            "org.offline-intelligence-hub.source-date-epoch"
                        )
                        if revision != spec.source_revision:
                            artifact_failures.append(
                                f"{artifact.artifact_id} source label mismatch: expected "
                                f"{spec.source_revision}, found {revision!r}"
                            )
                        if epoch != str(source_date_epoch):
                            artifact_failures.append(
                                f"{artifact.artifact_id} source-date label mismatch: expected "
                                f"{source_date_epoch}, found {epoch!r}"
                            )
                        identities.update(
                            {
                                "source_revision": revision or "",
                                "source_date_epoch": (
                                    int(epoch) if epoch and epoch.isdigit() else -1
                                ),
                            }
                        )
                    else:
                        identities["upstream_reference"] = artifact.upstream_reference
                except ReleaseProvenanceError as exc:
                    artifact_failures.append(f"{artifact.artifact_id}: {exc}")

            sbom_path, sbom_record = verify_payload(
                spec_path,
                artifact.sbom,
                label=f"{artifact.artifact_id} SBOM",
                failures=artifact_failures,
            )
            if sbom_record:
                payloads.append(sbom_record)
            if sbom_path.is_file():
                try:
                    subject_digest, component_count, inventory_digest = inspect_spdx(
                        sbom_path, artifact.sbom
                    )
                    identities.update(
                        {
                            "sbom_subject_manifest_sha256": subject_digest,
                            "sbom_component_count": component_count,
                            "normalized_component_inventory_sha256": inventory_digest,
                        }
                    )
                except ReleaseProvenanceError as exc:
                    artifact_failures.append(f"{artifact.artifact_id}: {exc}")

            native_identities: dict[str, str] = {}
            if isinstance(artifact, ProjectImageSpec):
                for binding in artifact.native_bindings:
                    inventory_path, inventory_record = verify_payload(
                        spec_path,
                        binding.inventory,
                        label=f"{artifact.artifact_id} native inventory {binding.component}",
                        failures=artifact_failures,
                    )
                    if inventory_record:
                        payloads.append(inventory_record)
                    if inventory_path.is_file():
                        try:
                            validate_native_binding(inventory_path, binding, artifact)
                            native_identities[binding.component] = binding.binary_sha256
                        except ReleaseProvenanceError as exc:
                            artifact_failures.append(str(exc))
            if native_identities:
                identities["native_binary_sha256"] = native_identities
        else:
            model_path, model_record = verify_payload(
                spec_path,
                artifact.payload,
                label=f"{artifact.artifact_id} model",
                failures=artifact_failures,
            )
            if model_record:
                payloads.append(model_record)
            _license_path, license_record = verify_payload(
                spec_path,
                artifact.license_evidence,
                label=f"{artifact.artifact_id} license evidence",
                failures=artifact_failures,
            )
            if license_record:
                payloads.append(license_record)
            identities.update(
                {
                    "model_id": artifact.model_id,
                    "model_revision": artifact.model_revision,
                    "format": artifact.format,
                    "payload_sha256": sha256_file(model_path)
                    if model_path.is_file()
                    else "",
                    "license_evidence_sha256": (
                        license_record.sha256 if license_record else ""
                    ),
                }
            )

        failures.extend(artifact_failures)
        artifacts.append(
            ArtifactRecord(
                artifact_id=artifact.artifact_id,
                artifact_type=artifact.artifact_type,
                payloads=payloads,
                identities=identities,
            )
        )

    return ReleaseProvenanceReport(
        status="failed" if failures else "passed",
        release_id=spec.release_id,
        app_version=spec.app_version,
        target_architecture=spec.target_architecture,
        source_revision=spec.source_revision,
        source_date_epoch=source_date_epoch,
        source_report_sha256=source_report_sha256,
        provenance_spec_sha256=sha256_file(spec_path),
        artifacts=artifacts,
        failures=failures,
    )


def write_release_provenance_report(
    report: ReleaseProvenanceReport, output: Path
) -> None:
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    output.write_text(payload, encoding="utf-8")


def format_release_provenance_summary(report: ReleaseProvenanceReport) -> str:
    lines = [
        f"Release artifact provenance: {'PASS' if report.passed else 'FAIL'}",
        f"Release: {report.release_id}",
        f"Source revision: {report.source_revision}",
        f"Artifacts: {len(report.artifacts)}",
    ]
    lines.extend(f"- {failure}" for failure in report.failures[:10])
    return "\n".join(lines)
