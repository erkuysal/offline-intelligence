from io import BytesIO
import json
from pathlib import Path
import stat
import subprocess
import tarfile
from types import SimpleNamespace

import pytest

from delivery.offline_bundle import BundleSpec, build_offline_bundle
from scripts.delivery import offline_operator as operator


IMAGE_ID = "sha256:" + "1" * 64


def build_operator_bundle(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    source = tmp_path / "source"
    source.mkdir()
    paths = sorted(operator.REQUIRED_PAYLOADS)
    inputs: list[dict[str, object]] = []
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
        else:
            content = f"payload:{relative}\n"
        file_path.write_text(content, encoding="utf-8")
        artifact_type = "container_image" if relative.startswith("images/") else (
            "model" if relative.startswith("models/") else "configuration"
        )
        origin = f"test:{relative}"
        if artifact_type == "container_image":
            reference = relative.removeprefix("images/").removesuffix(".tar") + ":test"
            origin = f"docker-image:{reference}@{IMAGE_ID}"
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
    spec = BundleSpec.model_validate(
        {
            "release_id": "offline-operator-test",
            "app_version": "0.4.0",
            "target_architecture": "linux-x86_64-cuda13",
            "inputs": inputs,
        }
    )
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(spec.model_dump_json(), encoding="utf-8")
    bundle = tmp_path / "bundle"
    manifest = build_offline_bundle(spec_path, bundle).model_dump(mode="json")
    return bundle, manifest


def completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_dependency_free_verifier_passes_and_detects_corruption(tmp_path: Path) -> None:
    bundle, _ = build_operator_bundle(tmp_path)

    _, report = operator.verify_bundle(bundle)
    assert report.passed is True

    (bundle / "models" / "chat-model.gguf").write_text("corrupt", encoding="utf-8")
    _, corrupt_report = operator.verify_bundle(bundle)
    assert corrupt_report.passed is False
    assert any(check.name == "payload_integrity" and not check.passed for check in corrupt_report.checks)


def test_dependency_free_verifier_rejects_bundle_directory_symlink(tmp_path: Path) -> None:
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

    def fake_run(command: list[str] | tuple[str, ...], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
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
    target_suffix = operator.hashlib.sha256(str(target.resolve()).encode()).hexdigest()[:8]
    assert project_name.endswith(target_suffix)
    assert (target / "models" / "chat-model.gguf").is_file()
    assert not any("up" in command for command in commands)
    assert all(command[:3] == ["docker", "load", "--input"] for command in commands if "load" in command)

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
    monkeypatch.setattr(operator, "run_command", lambda command, timeout=120: completed(f"{IMAGE_ID}\n") if list(command)[:3] == ["docker", "image", "inspect"] else completed())
    operator.install(bundle, target, manifest, start=False)
    state_path = target / "release.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["started"] = True
    state_path.write_text(json.dumps(state), encoding="utf-8")
    commands: list[list[str]] = []

    def stop_run(command: list[str] | tuple[str, ...], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
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
    assert report.checks == [operator.Check("bundle_verification", False, "bundle verification failed")]


def test_preflight_reports_measured_host_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _ = build_operator_bundle(tmp_path)
    monkeypatch.setattr(operator.platform, "system", lambda: "Linux")
    monkeypatch.setattr(operator.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(operator.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(operator, "run_command", lambda command, timeout=120: completed("29.0.0\n"))
    monkeypatch.setattr(operator, "available_memory_bytes", lambda: 16 * operator.GIB)
    monkeypatch.setattr(operator, "gpu_memory_bytes", lambda: 12 * operator.GIB)
    monkeypatch.setattr(operator.shutil, "disk_usage", lambda path: SimpleNamespace(free=100 * operator.GIB))
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
        lambda command, timeout=120: completed(f"{IMAGE_ID}\n")
        if list(command)[:3] == ["docker", "image", "inspect"]
        else completed(),
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
