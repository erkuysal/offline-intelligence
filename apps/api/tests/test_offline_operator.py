from io import BytesIO
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tarfile
from types import SimpleNamespace

import pytest

from delivery.offline_bundle import BundleSpec, build_offline_bundle
from delivery.release_signing import sign_bundle, write_signature
from scripts.delivery import offline_operator as operator


IMAGE_ID = "sha256:" + "1" * 64
SOURCE_REVISION = "2" * 40
SUBJECT_DIGEST = "3" * 64


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_tar_bytes(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mtime = 0
    archive.addfile(info, BytesIO(content))


def write_image_archive(path: Path, tag: str) -> str:
    config = b'{"config":{"Labels":{}}}'
    config_digest = hashlib.sha256(config).hexdigest()
    config_path = f"blobs/sha256/{config_digest}"
    manifest = json.dumps(
        [{"Config": config_path, "RepoTags": [tag], "Layers": []}],
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    with tarfile.open(path, "w") as archive:
        add_tar_bytes(archive, config_path, config)
        add_tar_bytes(archive, "manifest.json", manifest)
    return config_digest


def write_spdx(path: Path, subject_name: str) -> None:
    path.write_text(
        json.dumps(
            {
                "spdxVersion": "SPDX-2.3",
                "packages": [
                    {
                        "name": subject_name,
                        "primaryPackagePurpose": "CONTAINER",
                        "externalRefs": [
                            {
                                "referenceType": "purl",
                                "referenceLocator": (
                                    f"pkg:oci/{subject_name}@sha256%3A{SUBJECT_DIGEST}"
                                ),
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def build_operator_bundle(
    tmp_path: Path,
    *,
    release_id: str = "offline-operator-test",
    app_version: str = "0.4.0",
    directory_name: str = "operator-fixture",
) -> tuple[Path, dict[str, object]]:
    work = tmp_path / directory_name
    work.mkdir()
    source = work / "source"
    source.mkdir()
    paths = sorted(operator.REQUIRED_PAYLOADS)
    inputs: list[dict[str, object]] = []
    provenance_artifacts: list[dict[str, object]] = []
    for index, relative in enumerate(paths):
        file_path = source / f"input-{index}"
        if relative == "configs/prod.example.env":
            content = (
                "POSTGRES_PASSWORD=replace-with-a-strong-database-password\n"
                "JWT_SECRET_KEY=replace-with-a-long-random-secret\n"
                "POSTGRES_USER=offline_ai\n"
                "POSTGRES_DB=offline_ai\n"
                "MODEL_DIR=../var/models\n"
            )
        elif relative == "configs/compose.yaml":
            content = (
                "services:\n"
                "  web:\n"
                "    command: printf 'nameserver 127.0.0.1\\n' > /etc/resolv.conf\n"
                "networks:\n"
                "  application:\n"
                "    internal: true\n"
                "  edge:\n"
                "    driver_opts:\n"
                '      com.docker.network.bridge.enable_ip_masquerade: "false"\n'
            )
        elif not relative.startswith("images/"):
            content = f"payload:{relative}\n"
        if not relative.startswith("images/"):
            file_path.write_text(content, encoding="utf-8")
        artifact_type = (
            "container_image"
            if relative.startswith("images/")
            else ("model" if relative.startswith("models/") else "configuration")
        )
        origin = f"test:{relative}"
        if artifact_type == "container_image":
            reference = relative.removeprefix("images/").removesuffix(".tar") + ":test"
            origin = f"docker-image:{reference}@{IMAGE_ID}"
            config_digest = write_image_archive(file_path, reference)
            sbom_path = source / f"sbom-{index}.json"
            subject_name = f"test-image-{index}"
            write_spdx(sbom_path, subject_name)
            sbom_bundle_path = f"sbom/{subject_name}.spdx.json"
            inputs.append(
                {
                    "source": str(sbom_path),
                    "path": sbom_bundle_path,
                    "artifact_type": "sbom",
                    "version": "test",
                    "origin": f"test-syft:{reference}",
                    "contains_secrets": False,
                }
            )
            provenance_artifacts.append(
                {
                    "artifact_type": "external_container_image",
                    "artifact_id": subject_name,
                    "archive": {
                        "path": str(file_path.relative_to(work)),
                        "bundle_path": relative,
                        "sha256": file_digest(file_path),
                        "size_bytes": file_path.stat().st_size,
                    },
                    "repo_tags": [reference],
                    "image_index_sha256": IMAGE_ID.removeprefix("sha256:"),
                    "image_config_sha256": config_digest,
                    "upstream_reference": f"{reference}@{IMAGE_ID}",
                    "sbom": {
                        "path": str(sbom_path.relative_to(work)),
                        "bundle_path": sbom_bundle_path,
                        "sha256": file_digest(sbom_path),
                        "size_bytes": sbom_path.stat().st_size,
                        "format": "SPDX-2.3",
                        "package_count": 1,
                        "subject_name": subject_name,
                        "subject_manifest_sha256": SUBJECT_DIGEST,
                    },
                }
            )
        inputs.append(
            {
                "source": str(file_path),
                "path": relative,
                "artifact_type": artifact_type,
                "version": "test",
                "origin": origin,
                "contains_secrets": False,
            }
        )
    license_path = source / "license.md"
    license_path.write_text("test license evidence\n", encoding="utf-8")
    inputs.append(
        {
            "source": str(license_path),
            "path": "licenses/release-license-status.md",
            "artifact_type": "license",
            "version": "test",
            "origin": "test:license",
            "contains_secrets": False,
        }
    )
    for item in inputs:
        if item["artifact_type"] != "model":
            continue
        model_path = Path(str(item["source"]))
        artifact_id = Path(str(item["path"])).stem.replace("-", "_")
        provenance_artifacts.append(
            {
                "artifact_type": "model",
                "artifact_id": artifact_id,
                "payload": {
                    "path": str(model_path.relative_to(work)),
                    "bundle_path": item["path"],
                    "sha256": file_digest(model_path),
                    "size_bytes": model_path.stat().st_size,
                },
                "model_id": f"test/{artifact_id}",
                "model_revision": "test-revision",
                "format": "GGUF",
                "license_evidence": {
                    "path": str(license_path.relative_to(work)),
                    "bundle_path": "licenses/release-license-status.md",
                    "sha256": file_digest(license_path),
                    "size_bytes": license_path.stat().st_size,
                },
            }
        )
    migration_source = source / "migration"
    migration_source.write_text("migration source\n", encoding="utf-8")
    inputs.append(
        {
            "source": str(migration_source),
            "path": "migrations/migrations.tar",
            "artifact_type": "migration",
            "version": "20260714_0013",
            "origin": "test:migrations",
            "contains_secrets": False,
        }
    )
    source_report_path = work / "source-report.json"
    source_report_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "report_type": "release_source_preflight",
                "status": "passed",
                "source_root": "/clean/source",
                "source_revision": SOURCE_REVISION,
                "expected_revision": SOURCE_REVISION,
                "source_date_epoch": 1784758937,
                "git_tree_clean": True,
                "git_status_entries": [],
                "required_files": [],
                "forbidden_context_paths": [],
                "missing_dockerignore_patterns": [],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    provenance_spec_path = work / "provenance-spec.json"
    provenance_spec_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "spec_type": "release_artifact_provenance",
                "release_id": release_id,
                "app_version": app_version,
                "target_architecture": "linux-x86_64-cuda13",
                "source_revision": SOURCE_REVISION,
                "source_report_path": source_report_path.name,
                "artifacts": provenance_artifacts,
            }
        ),
        encoding="utf-8",
    )
    spec = BundleSpec.model_validate(
        {
            "schema_version": "1.1",
            "release_id": release_id,
            "app_version": app_version,
            "target_architecture": "linux-x86_64-cuda13",
            "provenance": {"spec": provenance_spec_path.name},
            "inputs": inputs,
        }
    )
    spec_path = work / "spec.json"
    spec_path.write_text(spec.model_dump_json(), encoding="utf-8")
    bundle = work / "bundle"
    manifest = build_offline_bundle(spec_path, bundle).model_dump(mode="json")
    return bundle, manifest


def completed(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def write_trust_material(
    tmp_path: Path,
    bundle: Path,
    manifest: dict[str, object],
    *,
    revoke_key: bool = False,
    revoke_release: bool = False,
) -> tuple[Path, Path, Path]:
    private_key = tmp_path / "release-private.pem"
    public_key = tmp_path / "release-public.pem"
    signature = tmp_path / "release-signature.json"
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
    envelope = sign_bundle(bundle, private_key, public_key)
    write_signature(envelope, signature)
    policy = tmp_path / "revocations.json"
    policy.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "policy_type": "offline_release_revocations",
                "revoked_key_ids": [envelope.key_id] if revoke_key else [],
                "revoked_release_ids": [manifest["release_id"]]
                if revoke_release
                else [],
            }
        ),
        encoding="utf-8",
    )
    return signature, public_key, policy


def test_dependency_free_release_authenticity_accepts_external_trust_root(
    tmp_path: Path,
) -> None:
    bundle, manifest = build_operator_bundle(tmp_path)
    signature, public_key, policy = write_trust_material(tmp_path, bundle, manifest)

    key_id = operator.verify_release_authenticity(
        bundle, manifest, signature, public_key, policy
    )

    assert key_id.startswith("sha256:")


@pytest.mark.parametrize("revocation", ["key", "release"])
def test_dependency_free_release_authenticity_rejects_revocation(
    tmp_path: Path, revocation: str
) -> None:
    bundle, manifest = build_operator_bundle(tmp_path)
    signature, public_key, policy = write_trust_material(
        tmp_path,
        bundle,
        manifest,
        revoke_key=revocation == "key",
        revoke_release=revocation == "release",
    )

    with pytest.raises(operator.OperatorError, match="revoked"):
        operator.verify_release_authenticity(
            bundle, manifest, signature, public_key, policy
        )


def test_required_signature_failure_precedes_host_checks_and_mutation(
    tmp_path: Path,
) -> None:
    bundle, _manifest = build_operator_bundle(tmp_path)
    target = tmp_path / "target"

    _manifest_value, report = operator.preflight(
        bundle,
        target,
        web_port=3000,
        minimum_ram_gib=8,
        minimum_vram_gib=6,
        disk_reserve_gib=10,
        require_signature=True,
    )

    assert report.passed is False
    assert [check.name for check in report.checks] == [
        "bundle_verification",
        "release_authenticity",
    ]
    assert not target.exists()


def test_dependency_free_verifier_passes_and_detects_corruption(tmp_path: Path) -> None:
    bundle, _ = build_operator_bundle(tmp_path)

    _, report = operator.verify_bundle(bundle)
    assert report.passed is True

    (bundle / "models" / "chat-model.gguf").write_text("corrupt", encoding="utf-8")
    _, corrupt_report = operator.verify_bundle(bundle)
    assert corrupt_report.passed is False
    assert any(
        check.name == "payload_integrity" and not check.passed
        for check in corrupt_report.checks
    )


def test_dependency_free_verifier_rejects_bundle_directory_symlink(
    tmp_path: Path,
) -> None:
    bundle, _ = build_operator_bundle(tmp_path)
    link = tmp_path / "bundle-link"
    link.symlink_to(bundle, target_is_directory=True)

    manifest, report = operator.verify_bundle(link)

    assert manifest is None
    assert report.passed is False


def test_install_generates_secrets_loads_only_bundle_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, manifest = build_operator_bundle(tmp_path)
    target = tmp_path / "target"
    commands: list[list[str]] = []

    def fake_run(
        command: list[str] | tuple[str, ...], *, timeout: int = 120
    ) -> subprocess.CompletedProcess[str]:
        del timeout
        command_list = list(command)
        commands.append(command_list)
        if command_list[:3] == ["docker", "image", "inspect"]:
            return completed(f"{IMAGE_ID}\n")
        return completed()

    monkeypatch.setattr(operator, "run_command", fake_run)

    operator.install(bundle, target, manifest, start=False)
    first_env = (target / "config" / "prod.env").read_text(encoding="utf-8")
    operator.validate_secrets(operator.parse_env(target / "config" / "prod.env"))
    assert stat.S_IMODE((target / "config" / "prod.env").stat().st_mode) == 0o600
    assert "replace-with" not in first_env
    project_name = operator.parse_env(target / "config" / "prod.env")[
        "COMPOSE_PROJECT_NAME"
    ]
    target_suffix = operator.hashlib.sha256(str(target.resolve()).encode()).hexdigest()[
        :8
    ]
    assert project_name.endswith(target_suffix)
    assert (target / "models" / "chat-model.gguf").is_file()
    assert not any("up" in command for command in commands)
    assert all(
        command[:3] == ["docker", "load", "--input"]
        for command in commands
        if "load" in command
    )

    commands.clear()
    operator.install(bundle, target, manifest, start=False)
    assert (target / "config" / "prod.env").read_text(encoding="utf-8") == first_env

    (target / "models" / "chat-model.gguf").write_text("drift", encoding="utf-8")
    with pytest.raises(operator.OperatorError, match="payload size mismatch"):
        operator.install(bundle, target, manifest, start=False)


def test_uninstall_preserves_target_and_records_stopped_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, manifest = build_operator_bundle(tmp_path)
    target = tmp_path / "target"
    monkeypatch.setattr(
        operator,
        "run_command",
        lambda command, timeout=120: (
            completed(f"{IMAGE_ID}\n")
            if list(command)[:3] == ["docker", "image", "inspect"]
            else completed()
        ),
    )
    operator.install(bundle, target, manifest, start=False)
    state_path = target / "release.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["started"] = True
    state_path.write_text(json.dumps(state), encoding="utf-8")
    commands: list[list[str]] = []

    def stop_run(
        command: list[str] | tuple[str, ...], *, timeout: int = 120
    ) -> subprocess.CompletedProcess[str]:
        del timeout
        commands.append(list(command))
        return completed()

    monkeypatch.setattr(operator, "run_command", stop_run)
    operator.uninstall(target)

    assert target.is_dir()
    assert (target / "models" / "chat-model.gguf").is_file()
    assert json.loads(state_path.read_text(encoding="utf-8"))["started"] is False
    assert commands[0][-2:] == ["down", "--remove-orphans"]
    assert "--volumes" not in commands[0]


def test_preflight_fails_closed_when_bundle_is_corrupt(tmp_path: Path) -> None:
    bundle, _ = build_operator_bundle(tmp_path)
    (bundle / "images" / "web.tar").write_text("corrupt", encoding="utf-8")

    manifest, report = operator.preflight(
        bundle,
        tmp_path / "target",
        web_port=3000,
        minimum_ram_gib=8,
        minimum_vram_gib=6,
        disk_reserve_gib=10,
    )

    assert manifest is not None
    assert report.passed is False
    assert report.checks == [
        operator.Check("bundle_verification", False, "bundle verification failed")
    ]


def test_preflight_reports_measured_host_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _ = build_operator_bundle(tmp_path)
    monkeypatch.setattr(operator.platform, "system", lambda: "Linux")
    monkeypatch.setattr(operator.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(operator.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        operator, "run_command", lambda command, timeout=120: completed("29.0.0\n")
    )
    monkeypatch.setattr(operator, "available_memory_bytes", lambda: 16 * operator.GIB)
    monkeypatch.setattr(operator, "gpu_memory_bytes", lambda: 12 * operator.GIB)
    monkeypatch.setattr(
        operator.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=100 * operator.GIB),
    )
    monkeypatch.setattr(operator, "port_available", lambda port: port == 3000)

    _, report = operator.preflight(
        bundle,
        tmp_path / "target",
        web_port=3000,
        minimum_ram_gib=8,
        minimum_vram_gib=6,
        disk_reserve_gib=10,
    )

    assert report.passed is True
    assert {check.name for check in report.checks} == {
        "bundle_verification",
        "platform",
        "docker",
        "docker_compose",
        "ram",
        "vram",
        "disk",
        "web_port",
    }


def test_placeholder_secrets_are_rejected() -> None:
    with pytest.raises(operator.OperatorError, match="POSTGRES_PASSWORD"):
        operator.validate_secrets(
            {
                "POSTGRES_PASSWORD": "replace-with-a-strong-database-password",
                "JWT_SECRET_KEY": "a" * 48,
            }
        )


def test_image_origins_must_be_immutable() -> None:
    manifest = {
        "files": [
            {
                "artifact_type": "container_image",
                "origin": "docker-image:example/test:latest",
            }
        ]
    }

    with pytest.raises(operator.OperatorError, match="not immutable"):
        operator.image_expectations(manifest)


def installed_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, dict[str, object]]:
    bundle, manifest = build_operator_bundle(tmp_path)
    target = tmp_path / "target"
    monkeypatch.setattr(
        operator,
        "run_command",
        lambda command, timeout=120: (
            completed(f"{IMAGE_ID}\n")
            if list(command)[:3] == ["docker", "image", "inspect"]
            else completed()
        ),
    )
    operator.install(bundle, target, manifest, start=False)
    return bundle, target, manifest


def fake_backup_output(
    command: list[str] | tuple[str, ...],
    output: Path,
    *,
    timeout: int,
) -> subprocess.CompletedProcess[bytes]:
    del timeout
    if "pg_dump" in command:
        output.write_bytes(b"PGDMP-test-database")
    else:
        with tarfile.open(output, mode="w") as archive:
            content = b"restorable document"
            member = tarfile.TarInfo("./documents/test.txt")
            member.size = len(content)
            archive.addfile(member, BytesIO(content))
    return subprocess.CompletedProcess([], 0, b"", b"")


def create_fake_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, dict[str, object]]:
    bundle, target, manifest = installed_target(tmp_path, monkeypatch)
    monkeypatch.setattr(operator, "start_backup_postgres", lambda target, values: None)
    monkeypatch.setattr(
        operator,
        "postgres_scalar",
        lambda target, values, query: "20260714_0013",
    )
    monkeypatch.setattr(operator, "run_to_file", fake_backup_output)
    backup = tmp_path / "backup"
    operator.create_backup(target, backup)
    return bundle, backup, manifest


def write_upgrade_policy(
    path: Path,
    *,
    source_release_id: str,
    target_release_id: str,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "policy_type": "offline_upgrade_policy",
                "policy_id": "test-upgrades-v1",
                "supported_pairs": [
                    {
                        "pair_id": "test_v0_4_0_to_v0_5_0",
                        "source": {
                            "release_id": source_release_id,
                            "app_version": "0.4.0",
                            "migration_revision": "20260714_0013",
                        },
                        "target": {
                            "release_id": target_release_id,
                            "app_version": "0.5.0",
                            "migration_revision": "20260714_0013",
                        },
                        "migration_mode": "same_revision",
                        "rollback_strategy": "blue_green_source_restart",
                        "rollback_allowed_before_acceptance": True,
                        "irreversible_migrations": [],
                        "maximum_backup_age_hours": 24,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def upgrade_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path, Path, Path, dict[str, object], Path]:
    source_release_id = "offline-test-0.4.0"
    target_release_id = "offline-test-0.5.0"
    source_bundle, source_manifest = build_operator_bundle(
        tmp_path,
        release_id=source_release_id,
        app_version="0.4.0",
        directory_name="source-release",
    )
    target_bundle, target_manifest = build_operator_bundle(
        tmp_path,
        release_id=target_release_id,
        app_version="0.5.0",
        directory_name="target-release",
    )
    source_target = tmp_path / "source-target"

    def fake_run(
        command: list[str] | tuple[str, ...], *, timeout: int = 120
    ) -> subprocess.CompletedProcess[str]:
        del timeout
        command_list = list(command)
        if command_list[:3] == ["docker", "image", "inspect"]:
            return completed(f"{IMAGE_ID}\n")
        return completed()

    monkeypatch.setattr(operator, "run_command", fake_run)
    operator.install(source_bundle, source_target, source_manifest, start=False)
    monkeypatch.setattr(operator, "start_backup_postgres", lambda target, values: None)

    def scalar(target: Path, values: dict[str, str], query: str) -> str:
        del target, values
        return "0" if "information_schema.tables" in query else "20260714_0013"

    monkeypatch.setattr(operator, "postgres_scalar", scalar)
    monkeypatch.setattr(operator, "run_to_file", fake_backup_output)
    monkeypatch.setattr(
        operator,
        "run_from_file",
        lambda command, source, timeout: subprocess.CompletedProcess([], 0, b"", b""),
    )
    monkeypatch.setattr(operator, "wait_for_postgres", lambda target, values: None)
    backup = tmp_path / "upgrade-backup"
    operator.create_backup(source_target, backup)
    policy = write_upgrade_policy(
        tmp_path / "upgrade-policy.json",
        source_release_id=source_release_id,
        target_release_id=target_release_id,
    )
    return (
        source_target,
        source_bundle,
        target_bundle,
        tmp_path / "target",
        backup,
        target_manifest,
        policy,
    )


def test_upgrade_policy_rejects_irreversible_migration_boundary(
    tmp_path: Path,
) -> None:
    policy_path = write_upgrade_policy(
        tmp_path / "upgrade-policy.json",
        source_release_id="source",
        target_release_id="target",
    )
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["supported_pairs"][0]["target"]["migration_revision"] = "newer"
    policy["supported_pairs"][0]["irreversible_migrations"] = ["newer"]
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(operator.OperatorError, match="unsupported migration boundary"):
        operator.load_upgrade_policy(policy_path)


def test_upgrade_preflight_requires_matching_backup_and_free_space(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _, _, target, backup, manifest, policy = upgrade_fixture(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        operator.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=100 * operator.GIB),
    )

    pair, report = operator.upgrade_preflight(
        source,
        target,
        manifest,
        backup,
        policy,
        disk_reserve_gib=10,
    )

    assert pair is not None
    assert report.passed is True
    assert {check.name for check in report.checks} == {
        "source_stopped",
        "isolated_target",
        "supported_pair",
        "pre_upgrade_backup",
        "backup_freshness",
        "upgrade_disk",
        "rollback_boundary",
    }

    monkeypatch.setattr(
        operator.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=1),
    )
    _, insufficient_report = operator.upgrade_preflight(
        source,
        target,
        manifest,
        backup,
        policy,
        disk_reserve_gib=10,
    )
    assert insufficient_report.passed is False
    assert (
        next(
            check
            for check in insufficient_report.checks
            if check.name == "upgrade_disk"
        ).passed
        is False
    )

    backup_manifest_path = backup / operator.BACKUP_MANIFEST_NAME
    backup_manifest = json.loads(backup_manifest_path.read_text(encoding="utf-8"))
    backup_manifest["created_at"] = "2020-01-01T00:00:00+00:00"
    backup_manifest_path.write_text(
        json.dumps(backup_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksums_path = backup / operator.BACKUP_CHECKSUMS_NAME
    checksum_lines = checksums_path.read_text(encoding="utf-8").splitlines()
    checksums_path.write_text(
        "\n".join(
            (
                f"{file_digest(backup_manifest_path)}  {operator.BACKUP_MANIFEST_NAME}"
                if line.endswith(f"  {operator.BACKUP_MANIFEST_NAME}")
                else line
            )
            for line in checksum_lines
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        operator.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=100 * operator.GIB),
    )
    _, stale_report = operator.upgrade_preflight(
        source,
        target,
        manifest,
        backup,
        policy,
        disk_reserve_gib=10,
    )
    assert (
        next(
            check for check in stale_report.checks if check.name == "backup_freshness"
        ).passed
        is False
    )


def test_blue_green_upgrade_and_rollback_preserve_source_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, source_bundle, bundle, target, backup, manifest, policy = upgrade_fixture(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        operator.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=100 * operator.GIB),
    )

    evidence = operator.perform_upgrade(
        source,
        target,
        bundle,
        manifest,
        backup,
        policy,
        disk_reserve_gib=10,
    )

    assert evidence["migration_before"] == "20260714_0013"
    assert evidence["migration_after"] == "20260714_0013"
    assert evidence["rollback_eligible"] is True
    assert (
        json.loads((source / "release.json").read_text(encoding="utf-8"))["started"]
        is False
    )
    assert (
        json.loads((target / "release.json").read_text(encoding="utf-8"))["started"]
        is True
    )

    rollback = operator.rollback_upgrade(source, target, backup, policy, source_bundle)

    assert rollback["source_release_id"] == "offline-test-0.4.0"
    assert rollback["migration_revision"] == "20260714_0013"
    assert (
        json.loads((source / "release.json").read_text(encoding="utf-8"))["started"]
        is True
    )
    assert (
        json.loads((target / "release.json").read_text(encoding="utf-8"))["started"]
        is False
    )


def test_accept_upgrade_closes_rollback_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, source_bundle, bundle, target, backup, manifest, policy = upgrade_fixture(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        operator.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=100 * operator.GIB),
    )
    operator.perform_upgrade(
        source,
        target,
        bundle,
        manifest,
        backup,
        policy,
        disk_reserve_gib=10,
    )

    accepted = operator.accept_upgrade(target)

    assert accepted["rollback_eligible"] is False
    assert accepted["accepted_at"] is not None
    with pytest.raises(operator.OperatorError, match="no longer rollback eligible"):
        operator.rollback_upgrade(source, target, backup, policy, source_bundle)


def test_backup_is_secret_free_self_verifying_and_detects_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, backup, _ = create_fake_backup(tmp_path, monkeypatch)

    manifest, report = operator.verify_backup(backup)

    assert manifest is not None
    assert report.passed is True
    configuration = json.loads(
        (backup / "metadata" / "configuration.json").read_text(encoding="utf-8")
    )
    assert not (operator.REQUIRED_SECRETS & set(configuration))
    assert manifest["migration_revision"] == "20260714_0013"

    (backup / "database" / "postgres.dump").write_bytes(b"corrupt")
    _, corrupt_report = operator.verify_backup(backup)
    assert corrupt_report.passed is False


def test_storage_archive_rejects_links(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.tar"
    with tarfile.open(archive_path, mode="w") as archive:
        member = tarfile.TarInfo("./documents/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        archive.addfile(member)

    with pytest.raises(operator.OperatorError, match="unsafe storage archive member"):
        operator.safe_storage_archive(archive_path)


def test_restore_requires_empty_matching_target_and_records_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, backup, manifest = create_fake_backup(tmp_path, monkeypatch)
    restore_target = tmp_path / "restore-target"
    operator.install(bundle, restore_target, manifest, start=False)
    monkeypatch.setattr(operator, "start_backup_postgres", lambda target, values: None)

    def scalar(target: Path, values: dict[str, str], query: str) -> str:
        del target, values
        return "0" if "information_schema.tables" in query else "20260714_0013"

    monkeypatch.setattr(operator, "postgres_scalar", scalar)
    monkeypatch.setattr(
        operator,
        "run_from_file",
        lambda command, source, timeout: subprocess.CompletedProcess([], 0, b"", b""),
    )
    result = operator.restore_backup(backup, restore_target)

    assert result["migration_revision"] == "20260714_0013"
    restored_state = json.loads(
        (restore_target / "release.json").read_text(encoding="utf-8")
    )
    assert restored_state["restored_from"] == result["backup_id"]

    monkeypatch.setattr(operator, "postgres_scalar", lambda target, values, query: "1")
    with pytest.raises(operator.OperatorError, match="database is not empty"):
        operator.restore_backup(backup, restore_target)
