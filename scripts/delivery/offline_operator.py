#!/usr/bin/env python3
"""Dependency-free verifier and installer for an Offline Intelligence Hub bundle."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any


GIB = 1024**3
RESERVED_PATHS = {"manifest.json", "checksums.sha256"}
REQUIRED_PAYLOADS = {
    "configs/compose.yaml",
    "configs/prod.example.env",
    "images/application.tar",
    "images/llama-cuda.tar",
    "images/postgres.tar",
    "images/redis.tar",
    "images/web.tar",
    "models/chat-model.gguf",
    "models/embedding-model.gguf",
}
REQUIRED_SECRETS = {"POSTGRES_PASSWORD", "JWT_SECRET_KEY"}
PLACEHOLDER_MARKERS = ("replace-with", "change-me", "changeme", "example-secret")
IMAGE_ORIGIN_PATTERN = re.compile(
    r"^docker-images?:(?P<references>[^@]+)@(?P<image_id>sha256:[a-f0-9]{64})$"
)
BACKUP_MANIFEST_NAME = "backup-manifest.json"
BACKUP_CHECKSUMS_NAME = "backup-checksums.sha256"
BACKUP_RESERVED_PATHS = {BACKUP_MANIFEST_NAME, BACKUP_CHECKSUMS_NAME}
BACKUP_PAYLOADS = {
    "database/postgres.dump",
    "storage/api-storage.tar",
    "metadata/configuration.json",
    "metadata/release.json",
}


class OperatorError(RuntimeError):
    pass


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Report:
    report_type: str
    passed: bool
    checks: list[Check]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in value
    ):
        raise OperatorError(f"unsafe bundle path: {value!r}")


def load_manifest(bundle: Path) -> dict[str, Any]:
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise OperatorError("manifest.json is missing or is not a regular file")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorError(f"invalid manifest.json: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("manifest_type") != "offline_release_bundle":
        raise OperatorError("unsupported manifest type")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise OperatorError("manifest files must be a non-empty list")
    paths: list[str] = []
    for record in files:
        if not isinstance(record, dict):
            raise OperatorError("manifest file record must be an object")
        path = record.get("path")
        digest = record.get("sha256")
        size = record.get("size_bytes")
        if not isinstance(path, str):
            raise OperatorError("manifest path must be a string")
        validate_relative_path(path)
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise OperatorError(f"invalid digest for {path}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise OperatorError(f"invalid size for {path}")
        paths.append(path)
    if len(paths) != len(set(paths)):
        raise OperatorError("manifest contains duplicate paths")
    return manifest


def parse_checksums(
    path: Path,
    reserved_paths: set[str] = RESERVED_PATHS,
) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise OperatorError("checksums.sha256 is missing or is not a regular file")
    records: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if len(line) < 67 or line[64:66] != "  ":
            raise OperatorError(f"invalid checksum line {number}")
        digest, name = line[:64], line[66:]
        if not re.fullmatch(r"[a-f0-9]{64}", digest) or not name or name in records:
            raise OperatorError(f"invalid checksum line {number}")
        if name not in reserved_paths:
            validate_relative_path(name)
        records[name] = digest
    return records


def verify_bundle(bundle: Path) -> tuple[dict[str, Any] | None, Report]:
    bundle = bundle.expanduser().absolute()
    checks: list[Check] = []
    if bundle.is_symlink() or not bundle.is_dir():
        return None, Report("offline_bundle_verification", False, [Check("bundle", False, "not a regular directory")])
    try:
        manifest = load_manifest(bundle)
    except OperatorError as exc:
        return None, Report("offline_bundle_verification", False, [Check("manifest", False, str(exc))])

    records = manifest["files"]
    expected_files = {record["path"] for record in records} | RESERVED_PATHS
    expected_directories = {
        parent.as_posix()
        for record in records
        for parent in PurePosixPath(record["path"]).parents
        if parent.as_posix() != "."
    }
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    symlinks: list[str] = []
    for path in bundle.rglob("*"):
        relative = path.relative_to(bundle).as_posix()
        if path.is_symlink():
            symlinks.append(relative)
            actual_files.add(relative)
        elif path.is_file():
            actual_files.add(relative)
        elif path.is_dir():
            actual_directories.add(relative)
    tree_failures = [f"symlink: {path}" for path in sorted(symlinks)]
    tree_failures.extend(f"missing file: {path}" for path in sorted(expected_files - actual_files))
    tree_failures.extend(f"unexpected file: {path}" for path in sorted(actual_files - expected_files))
    tree_failures.extend(
        f"unexpected directory: {path}" for path in sorted(actual_directories - expected_directories)
    )
    checks.append(Check("exact_tree", not tree_failures, "; ".join(tree_failures) or "exact tree matched"))

    payload_failures: list[str] = []
    expected_checksums: dict[str, str] = {}
    for record in records:
        relative = record["path"]
        path = bundle.joinpath(*PurePosixPath(relative).parts)
        if path.is_symlink() or not path.is_file():
            continue
        size = path.stat().st_size
        digest = sha256_file(path)
        expected_checksums[relative] = record["sha256"]
        if size != record["size_bytes"]:
            payload_failures.append(f"size mismatch: {relative}")
        if not secrets.compare_digest(digest, record["sha256"]):
            payload_failures.append(f"checksum mismatch: {relative}")
    checks.append(Check("payload_integrity", not payload_failures, "; ".join(payload_failures) or "all payloads matched"))

    expected_checksums["manifest.json"] = sha256_file(bundle / "manifest.json")
    try:
        inventory = parse_checksums(bundle / "checksums.sha256")
        inventory_ok = inventory == expected_checksums
        inventory_detail = "checksum inventory matched" if inventory_ok else "checksum inventory differs from manifest"
    except OperatorError as exc:
        inventory_ok = False
        inventory_detail = str(exc)
    checks.append(Check("checksum_inventory", inventory_ok, inventory_detail))

    missing_required = sorted(REQUIRED_PAYLOADS - {record["path"] for record in records})
    checks.append(
        Check(
            "required_payloads",
            not missing_required,
            "all required payloads present" if not missing_required else f"missing: {', '.join(missing_required)}",
        )
    )
    compose_path = bundle / "configs" / "compose.yaml"
    try:
        compose_text = compose_path.read_text(encoding="utf-8")
        compose_failures = []
        if "internal: true" not in compose_text:
            compose_failures.append("application network is not internal")
        if 'com.docker.network.bridge.enable_ip_masquerade: "false"' not in compose_text:
            compose_failures.append("edge masquerading is not disabled")
        if "nameserver 127.0.0.1" not in compose_text:
            compose_failures.append("web runtime DNS lockdown is missing")
        if "host.docker.internal" in compose_text or "extra_hosts:" in compose_text:
            compose_failures.append("host gateway access is configured")
    except OSError as exc:
        compose_failures = [str(exc)]
    checks.append(
        Check(
            "compose_network_policy",
            not compose_failures,
            "; ".join(compose_failures) or "offline network policy present",
        )
    )
    total = sum(record["size_bytes"] for record in records)
    total_ok = manifest.get("total_size_bytes") == total
    checks.append(Check("manifest_total", total_ok, f"declared={manifest.get('total_size_bytes')}, calculated={total}"))
    return manifest, Report("offline_bundle_verification", all(check.passed for check in checks), checks)


def run_command(command: Sequence[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)


def run_to_file(command: Sequence[str], output: Path, *, timeout: int) -> subprocess.CompletedProcess[bytes]:
    with output.open("wb") as handle:
        return subprocess.run(command, check=False, stdout=handle, stderr=subprocess.PIPE, timeout=timeout)


def run_from_file(command: Sequence[str], source: Path, *, timeout: int) -> subprocess.CompletedProcess[bytes]:
    with source.open("rb") as handle:
        return subprocess.run(command, check=False, stdin=handle, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def available_memory_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def gpu_memory_bytes() -> int:
    if shutil.which("nvidia-smi") is None:
        return 0
    result = run_command(
        ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
        timeout=15,
    )
    if result.returncode != 0:
        return 0
    values = [int(value.strip()) for value in result.stdout.splitlines() if value.strip().isdigit()]
    return max(values, default=0) * 1024**2


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            handle.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def nearest_existing_parent(path: Path) -> Path:
    candidate = path.expanduser().absolute()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def preflight(
    bundle: Path,
    target: Path,
    *,
    web_port: int,
    minimum_ram_gib: int,
    minimum_vram_gib: int,
    disk_reserve_gib: int,
    check_port: bool = True,
) -> tuple[dict[str, Any] | None, Report]:
    manifest, verification = verify_bundle(bundle)
    checks = [Check("bundle_verification", verification.passed, "bundle verified" if verification.passed else "bundle verification failed")]
    if manifest is None or not verification.passed:
        return manifest, Report("offline_install_preflight", False, checks)

    system = platform.system()
    machine = platform.machine().lower()
    checks.append(Check("platform", system == "Linux" and machine in {"x86_64", "amd64"}, f"system={system}, architecture={machine}"))

    docker = run_command(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=30) if shutil.which("docker") else None
    docker_ok = docker is not None and docker.returncode == 0
    docker_detail = docker.stdout.strip() if docker_ok and docker is not None else (docker.stderr.strip() if docker is not None else "docker not found")
    checks.append(Check("docker", docker_ok, docker_detail or "Docker daemon unavailable"))

    compose = run_command(["docker", "compose", "version", "--short"], timeout=30) if shutil.which("docker") else None
    compose_ok = compose is not None and compose.returncode == 0
    compose_detail = compose.stdout.strip() if compose_ok and compose is not None else (compose.stderr.strip() if compose is not None else "docker not found")
    checks.append(Check("docker_compose", compose_ok, compose_detail or "Compose unavailable"))

    available_ram = available_memory_bytes()
    required_ram = minimum_ram_gib * GIB
    checks.append(Check("ram", available_ram >= required_ram, f"available={available_ram}, required={required_ram}"))

    available_vram = gpu_memory_bytes()
    required_vram = minimum_vram_gib * GIB
    checks.append(Check("vram", available_vram >= required_vram, f"available={available_vram}, required={required_vram}"))

    disk_root = nearest_existing_parent(target)
    free_disk = shutil.disk_usage(disk_root).free
    required_disk = int(manifest["total_size_bytes"]) * 2 + disk_reserve_gib * GIB
    checks.append(Check("disk", free_disk >= required_disk, f"free={free_disk}, required={required_disk}, root={disk_root}"))

    port_ok = not check_port or port_available(web_port)
    checks.append(Check("web_port", port_ok, f"port={web_port}, checked={check_port}"))
    return manifest, Report("offline_install_preflight", all(check.passed for check in checks), checks)


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise OperatorError(f"invalid environment line {number}")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise OperatorError(f"invalid environment key on line {number}")
        if key in values:
            raise OperatorError(f"duplicate environment key on line {number}: {key}")
        values[key] = value
    return values


def validate_secrets(values: dict[str, str]) -> None:
    for key in REQUIRED_SECRETS:
        value = values.get(key, "")
        lowered = value.lower()
        if len(value) < 24 or any(marker in lowered for marker in PLACEHOLDER_MARKERS):
            raise OperatorError(f"{key} is missing, too short, or still a placeholder")


def render_target_env(example: Path, target: Path, release_id: str) -> str:
    values = parse_env(example)
    values["POSTGRES_PASSWORD"] = secrets.token_urlsafe(36)
    values["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)
    values["MODEL_DIR"] = str((target / "models").resolve())
    project_base = re.sub(r"[^a-z0-9_-]", "-", release_id.lower()).strip("-_")
    target_suffix = hashlib.sha256(str(target.resolve()).encode()).hexdigest()[:8]
    values["COMPOSE_PROJECT_NAME"] = f"{project_base[:54]}-{target_suffix}"
    validate_secrets(values)
    return "".join(f"{key}={value}\n" for key, value in values.items())


def image_expectations(manifest: dict[str, Any]) -> dict[str, str]:
    expectations: dict[str, str] = {}
    for record in manifest["files"]:
        if record.get("artifact_type") != "container_image":
            continue
        origin = record.get("origin", "")
        match = IMAGE_ORIGIN_PATTERN.fullmatch(origin)
        if match is None:
            raise OperatorError(f"container image origin is not immutable: {origin}")
        for reference in match.group("references").split(","):
            expectations[reference] = match.group("image_id")
    return expectations


def compose_command(target: Path, *arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(target / "config" / "prod.env"),
        "-f",
        str(target / "compose.yaml"),
        *arguments,
    ]


def require_installed_payloads(
    bundle: Path,
    target: Path,
    manifest: dict[str, Any],
) -> None:
    installed_paths = {
        "configs/compose.yaml": target / "compose.yaml",
        "configs/prod.example.env": target / "config" / "prod.example.env",
        "models/chat-model.gguf": target / "models" / "chat-model.gguf",
        "models/embedding-model.gguf": target / "models" / "embedding-model.gguf",
    }
    records = {record["path"]: record for record in manifest["files"]}
    for bundle_path, installed_path in installed_paths.items():
        record = records[bundle_path]
        if installed_path.is_symlink() or not installed_path.is_file():
            raise OperatorError(f"installed payload is missing or unsafe: {installed_path}")
        if installed_path.stat().st_size != record["size_bytes"]:
            raise OperatorError(f"installed payload size mismatch: {installed_path}")
        if not secrets.compare_digest(sha256_file(installed_path), record["sha256"]):
            raise OperatorError(f"installed payload checksum mismatch: {installed_path}")
        if not secrets.compare_digest(
            sha256_file(bundle.joinpath(*PurePosixPath(bundle_path).parts)),
            record["sha256"],
        ):
            raise OperatorError(f"bundle payload changed after verification: {bundle_path}")


def release_state(manifest: dict[str, Any], *, started: bool) -> dict[str, Any]:
    models = {
        record["path"]: record["sha256"]
        for record in manifest["files"]
        if record.get("artifact_type") == "model"
    }
    migration_versions = [
        record["version"]
        for record in manifest["files"]
        if record.get("artifact_type") == "migration"
    ]
    return {
        "release_id": manifest["release_id"],
        "app_version": manifest["app_version"],
        "started": started,
        "model_sha256": models,
        "image_ids": image_expectations(manifest),
        "migration_head": migration_versions[-1] if migration_versions else None,
    }


def install(bundle: Path, target: Path, manifest: dict[str, Any], *, start: bool) -> None:
    bundle = bundle.resolve()
    target = target.expanduser().absolute()
    state_path = target / "release.json"
    if target.exists():
        if target.is_symlink() or not state_path.is_file():
            raise OperatorError(f"existing target is not a managed installation: {target}")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("release_id") != manifest.get("release_id"):
            raise OperatorError("existing target belongs to a different release")
        validate_secrets(parse_env(target / "config" / "prod.env"))
        require_installed_payloads(bundle, target, manifest)
        expected_state = release_state(manifest, started=bool(state.get("started")))
        for key in ("model_sha256", "image_ids", "migration_head"):
            if key in state and state[key] != expected_state[key]:
                raise OperatorError(f"existing target identity mismatch: {key}")
            state[key] = expected_state[key]
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
        try:
            (staging / "config").mkdir()
            (staging / "models").mkdir()
            shutil.copyfile(bundle / "configs" / "compose.yaml", staging / "compose.yaml")
            shutil.copyfile(bundle / "configs" / "prod.example.env", staging / "config" / "prod.example.env")
            shutil.copyfile(bundle / "models" / "chat-model.gguf", staging / "models" / "chat-model.gguf")
            shutil.copyfile(bundle / "models" / "embedding-model.gguf", staging / "models" / "embedding-model.gguf")
            env_path = staging / "config" / "prod.env"
            env_path.write_text(
                render_target_env(
                    bundle / "configs" / "prod.example.env",
                    target,
                    str(manifest["release_id"]),
                ),
                encoding="utf-8",
            )
            env_path.chmod(0o600)
            state_path_in_staging = staging / "release.json"
            state_path_in_staging.write_text(
                json.dumps(release_state(manifest, started=False), indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    require_installed_payloads(bundle, target, manifest)

    for archive in sorted((bundle / "images").glob("*.tar")):
        result = run_command(["docker", "load", "--input", str(archive)], timeout=900)
        if result.returncode != 0:
            raise OperatorError(f"docker load failed for {archive.name}: {result.stderr.strip()}")

    for reference, expected_id in image_expectations(manifest).items():
        result = run_command(
            ["docker", "image", "inspect", reference, "--format", "{{.Id}}"],
            timeout=30,
        )
        actual_id = result.stdout.strip() if result.returncode == 0 else ""
        if not secrets.compare_digest(actual_id, expected_id):
            raise OperatorError(
                f"image identity mismatch for {reference}: expected {expected_id}, "
                f"found {actual_id or 'missing'}"
            )

    config = run_command(compose_command(target, "config", "--quiet"), timeout=60)
    if config.returncode != 0:
        raise OperatorError(f"Compose configuration is invalid: {config.stderr.strip()}")
    if start:
        result = run_command(
            compose_command(target, "up", "-d", "--no-build", "--pull", "never"),
            timeout=900,
        )
        if result.returncode != 0:
            raise OperatorError(f"Compose start failed: {result.stderr.strip()}")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["started"] = True
        state_path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def managed_target(target: Path) -> tuple[Path, dict[str, str], dict[str, Any]]:
    target = target.expanduser().absolute()
    state_path = target / "release.json"
    env_path = target / "config" / "prod.env"
    if target.is_symlink() or not state_path.is_file() or env_path.is_symlink() or not env_path.is_file():
        raise OperatorError(f"target is not a managed installation: {target}")
    values = parse_env(env_path)
    validate_secrets(values)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for key in ("release_id", "app_version", "model_sha256", "image_ids", "migration_head"):
        if key not in state:
            raise OperatorError(f"managed target is missing recovery identity: {key}")
    return target, values, state


def wait_for_postgres(target: Path, values: dict[str, str]) -> None:
    command = compose_command(
        target,
        "exec",
        "-T",
        "postgres",
        "pg_isready",
        "-U",
        values["POSTGRES_USER"],
        "-d",
        values["POSTGRES_DB"],
    )
    for _ in range(60):
        if run_command(command, timeout=10).returncode == 0:
            return
        time.sleep(1)
    raise OperatorError("PostgreSQL did not become ready within 60 seconds")


def start_backup_postgres(target: Path, values: dict[str, str]) -> None:
    result = run_command(
        compose_command(target, "up", "-d", "--no-build", "--pull", "never", "postgres"),
        timeout=300,
    )
    if result.returncode != 0:
        raise OperatorError(f"failed to start PostgreSQL for recovery operation: {result.stderr.strip()}")
    wait_for_postgres(target, values)


def postgres_scalar(target: Path, values: dict[str, str], query: str) -> str:
    result = run_command(
        compose_command(
            target,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            values["POSTGRES_USER"],
            "-d",
            values["POSTGRES_DB"],
            "-At",
            "-c",
            query,
        ),
        timeout=60,
    )
    if result.returncode != 0:
        raise OperatorError(f"PostgreSQL query failed: {result.stderr.strip()}")
    return result.stdout.strip()


def safe_storage_archive(path: Path) -> None:
    try:
        with tarfile.open(path, mode="r:") as archive:
            for member in archive.getmembers():
                name = member.name.removeprefix("./")
                if name and name != ".":
                    validate_relative_path(name.rstrip("/"))
                if member.issym() or member.islnk() or member.isdev():
                    raise OperatorError(f"unsafe storage archive member: {member.name}")
    except (OSError, tarfile.TarError) as exc:
        raise OperatorError(f"invalid storage archive: {exc}") from exc


def create_backup(target: Path, output: Path) -> dict[str, Any]:
    target, values, state = managed_target(target)
    output = output.expanduser().absolute()
    if output.exists():
        raise OperatorError(f"backup output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    started_before = bool(state.get("started"))
    started_at = time.perf_counter()
    try:
        for directory in ("database", "storage", "metadata"):
            (staging / directory).mkdir()
        start_backup_postgres(target, values)
        migration_revision = postgres_scalar(target, values, "SELECT version_num FROM alembic_version")
        if migration_revision != state["migration_head"]:
            raise OperatorError(
                f"migration identity mismatch: installed={state['migration_head']}, database={migration_revision}"
            )

        database_path = staging / "database" / "postgres.dump"
        database_result = run_to_file(
            compose_command(
                target,
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "-U",
                values["POSTGRES_USER"],
                "-d",
                values["POSTGRES_DB"],
                "--format=custom",
                "--no-owner",
                "--no-privileges",
            ),
            database_path,
            timeout=900,
        )
        if database_result.returncode != 0:
            raise OperatorError(f"pg_dump failed: {database_result.stderr.decode(errors='replace').strip()}")

        storage_path = staging / "storage" / "api-storage.tar"
        storage_result = run_to_file(
            compose_command(
                target,
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "tar",
                "api",
                "-C",
                "/app/storage",
                "-cf",
                "-",
                ".",
            ),
            storage_path,
            timeout=900,
        )
        if storage_result.returncode != 0:
            raise OperatorError(
                f"document storage archive failed: {storage_result.stderr.decode(errors='replace').strip()}"
            )
        safe_storage_archive(storage_path)

        configuration = {
            key: value for key, value in values.items() if key not in REQUIRED_SECRETS
        }
        (staging / "metadata" / "configuration.json").write_text(
            json.dumps(configuration, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        recovery_state = {
            key: state[key]
            for key in ("release_id", "app_version", "model_sha256", "image_ids", "migration_head")
        }
        (staging / "metadata" / "release.json").write_text(
            json.dumps(recovery_state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        records: list[dict[str, Any]] = []
        for relative in sorted(BACKUP_PAYLOADS):
            path = staging.joinpath(*PurePosixPath(relative).parts)
            records.append(
                {
                    "path": relative,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        created_at = datetime.now(UTC)
        manifest = {
            "schema_version": "1.0",
            "manifest_type": "offline_recovery_backup",
            "backup_id": f"{created_at.strftime('%Y%m%dT%H%M%SZ')}-{state['release_id']}",
            "created_at": created_at.isoformat(),
            "release_id": state["release_id"],
            "app_version": state["app_version"],
            "migration_revision": migration_revision,
            "model_sha256": state["model_sha256"],
            "image_ids": state["image_ids"],
            "files": records,
            "total_size_bytes": sum(record["size_bytes"] for record in records),
            "duration_seconds": round(time.perf_counter() - started_at, 3),
            "contains_target_secrets": False,
            "contains_sensitive_data": True,
        }
        manifest_path = staging / BACKUP_MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        checksum_records = [(record["sha256"], record["path"]) for record in records]
        checksum_records.append((sha256_file(manifest_path), BACKUP_MANIFEST_NAME))
        (staging / BACKUP_CHECKSUMS_NAME).write_text(
            "".join(f"{digest}  {path}\n" for digest, path in checksum_records),
            encoding="utf-8",
        )
        for path in staging.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
        staging.chmod(0o700)
        os.replace(staging, output)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        if not started_before:
            run_command(compose_command(target, "stop", "postgres"), timeout=120)


def verify_backup(backup: Path) -> tuple[dict[str, Any] | None, Report]:
    backup = backup.expanduser().absolute()
    checks: list[Check] = []
    if backup.is_symlink() or not backup.is_dir():
        return None, Report("offline_backup_verification", False, [Check("backup", False, "not a regular directory")])
    manifest_path = backup / BACKUP_MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("manifest_type") != "offline_recovery_backup":
            raise OperatorError("unsupported backup manifest type")
        records = manifest["files"]
        if {record["path"] for record in records} != BACKUP_PAYLOADS:
            raise OperatorError("backup payload inventory is incomplete")
    except (OSError, KeyError, TypeError, json.JSONDecodeError, OperatorError) as exc:
        return None, Report("offline_backup_verification", False, [Check("manifest", False, str(exc))])

    expected_files = BACKUP_PAYLOADS | BACKUP_RESERVED_PATHS
    expected_directories = {PurePosixPath(path).parent.as_posix() for path in BACKUP_PAYLOADS}
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    tree_failures: list[str] = []
    for path in backup.rglob("*"):
        relative = path.relative_to(backup).as_posix()
        if path.is_symlink():
            tree_failures.append(f"symlink: {relative}")
            actual_files.add(relative)
        elif path.is_file():
            actual_files.add(relative)
        elif path.is_dir():
            actual_directories.add(relative)
    tree_failures.extend(f"missing file: {path}" for path in sorted(expected_files - actual_files))
    tree_failures.extend(f"unexpected file: {path}" for path in sorted(actual_files - expected_files))
    tree_failures.extend(
        f"unexpected directory: {path}" for path in sorted(actual_directories - expected_directories)
    )
    checks.append(Check("exact_tree", not tree_failures, "; ".join(tree_failures) or "exact tree matched"))

    integrity_failures: list[str] = []
    expected_checksums: dict[str, str] = {}
    for record in records:
        path = backup.joinpath(*PurePosixPath(record["path"]).parts)
        if not path.is_file() or path.is_symlink():
            continue
        digest = sha256_file(path)
        expected_checksums[record["path"]] = record["sha256"]
        if path.stat().st_size != record["size_bytes"]:
            integrity_failures.append(f"size mismatch: {record['path']}")
        if not secrets.compare_digest(digest, record["sha256"]):
            integrity_failures.append(f"checksum mismatch: {record['path']}")
    checks.append(Check("payload_integrity", not integrity_failures, "; ".join(integrity_failures) or "all payloads matched"))

    expected_checksums[BACKUP_MANIFEST_NAME] = sha256_file(manifest_path)
    try:
        inventory = parse_checksums(backup / BACKUP_CHECKSUMS_NAME, BACKUP_RESERVED_PATHS)
        inventory_ok = inventory == expected_checksums
    except (OSError, OperatorError) as exc:
        inventory_ok = False
        integrity_failures = [str(exc)]
    checks.append(Check("checksum_inventory", inventory_ok, "checksum inventory matched" if inventory_ok else "; ".join(integrity_failures)))

    try:
        safe_storage_archive(backup / "storage" / "api-storage.tar")
        archive_ok = True
        archive_detail = "storage archive members are safe"
    except OperatorError as exc:
        archive_ok = False
        archive_detail = str(exc)
    checks.append(Check("storage_archive", archive_ok, archive_detail))

    configuration = json.loads((backup / "metadata" / "configuration.json").read_text(encoding="utf-8"))
    secrets_absent = (
        not (REQUIRED_SECRETS & set(configuration))
        and manifest.get("contains_target_secrets") is False
        and manifest.get("contains_sensitive_data") is True
    )
    checks.append(
        Check(
            "target_secrets_absent",
            secrets_absent,
            "no target secrets present" if secrets_absent else "target secret metadata found",
        )
    )
    private_permissions = backup.stat().st_mode & 0o077 == 0
    checks.append(
        Check(
            "private_permissions",
            private_permissions,
            "backup root is private" if private_permissions else "backup root grants group/world access",
        )
    )
    return manifest, Report("offline_backup_verification", all(check.passed for check in checks), checks)


def restore_backup(backup: Path, target: Path) -> dict[str, Any]:
    manifest, report = verify_backup(backup)
    if manifest is None or not report.passed:
        raise OperatorError("backup verification failed")
    backup = backup.expanduser().absolute()
    target, values, state = managed_target(target)
    for key in ("release_id", "app_version", "model_sha256", "image_ids", "migration_head"):
        backup_value = manifest["migration_revision"] if key == "migration_head" else manifest[key]
        if state[key] != backup_value:
            raise OperatorError(f"backup target identity mismatch: {key}")
    if state.get("started"):
        raise OperatorError("restore target must be stopped")

    started_at = time.perf_counter()
    start_backup_postgres(target, values)
    try:
        table_count = postgres_scalar(
            target,
            values,
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'",
        )
        if table_count != "0":
            raise OperatorError(f"restore database is not empty: {table_count} public tables")
        storage_empty = run_command(
            compose_command(
                target,
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "/bin/sh",
                "api",
                "-ec",
                'test -z "$(find /app/storage -mindepth 1 -print -quit)"',
            ),
            timeout=120,
        )
        if storage_empty.returncode != 0:
            raise OperatorError("restore document storage is not empty")

        database_result = run_from_file(
            compose_command(
                target,
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "-U",
                values["POSTGRES_USER"],
                "-d",
                values["POSTGRES_DB"],
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
            ),
            backup / "database" / "postgres.dump",
            timeout=900,
        )
        if database_result.returncode != 0:
            raise OperatorError(f"pg_restore failed: {database_result.stderr.decode(errors='replace').strip()}")

        storage_result = run_from_file(
            compose_command(
                target,
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "tar",
                "api",
                "-C",
                "/app/storage",
                "-xf",
                "-",
            ),
            backup / "storage" / "api-storage.tar",
            timeout=900,
        )
        if storage_result.returncode != 0:
            raise OperatorError(f"storage restore failed: {storage_result.stderr.decode(errors='replace').strip()}")

        restored_revision = postgres_scalar(target, values, "SELECT version_num FROM alembic_version")
        if restored_revision != manifest["migration_revision"]:
            raise OperatorError(
                f"restored migration mismatch: expected {manifest['migration_revision']}, found {restored_revision}"
            )
        state["restored_from"] = manifest["backup_id"]
        state["restore_duration_seconds"] = round(time.perf_counter() - started_at, 3)
        (target / "release.json").write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {
            "backup_id": manifest["backup_id"],
            "migration_revision": restored_revision,
            "duration_seconds": state["restore_duration_seconds"],
        }
    finally:
        run_command(compose_command(target, "stop", "postgres"), timeout=120)


def uninstall(target: Path) -> None:
    target = target.expanduser().absolute()
    state_path = target / "release.json"
    if target.is_symlink() or not state_path.is_file():
        raise OperatorError(f"target is not a managed installation: {target}")
    validate_secrets(parse_env(target / "config" / "prod.env"))
    result = run_command(compose_command(target, "down", "--remove-orphans"), timeout=300)
    if result.returncode != 0:
        raise OperatorError(f"Compose stop failed: {result.stderr.strip()}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["started"] = False
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_report(report: Report, output: str | None) -> None:
    payload = json.dumps(asdict(report), indent=2, sort_keys=True) + "\n"
    if output:
        Path(output).write_text(payload, encoding="utf-8")
    print(payload, end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--bundle", required=True)
    verify_parser.add_argument("--output")
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--bundle", required=True)
    preflight_parser.add_argument("--target", required=True)
    preflight_parser.add_argument("--web-port", type=int, default=3000)
    preflight_parser.add_argument("--minimum-ram-gib", type=int, default=8)
    preflight_parser.add_argument("--minimum-vram-gib", type=int, default=6)
    preflight_parser.add_argument("--disk-reserve-gib", type=int, default=10)
    preflight_parser.add_argument("--output")
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--bundle", required=True)
    install_parser.add_argument("--target", required=True)
    install_parser.add_argument("--web-port", type=int, default=3000)
    install_parser.add_argument("--minimum-ram-gib", type=int, default=8)
    install_parser.add_argument("--minimum-vram-gib", type=int, default=6)
    install_parser.add_argument("--disk-reserve-gib", type=int, default=10)
    install_parser.add_argument("--no-start", action="store_true")
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--target", required=True)
    backup_parser.add_argument("--output", required=True)
    backup_verify_parser = subparsers.add_parser("backup-verify")
    backup_verify_parser.add_argument("--backup", required=True)
    backup_verify_parser.add_argument("--output")
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup", required=True)
    restore_parser.add_argument("--target", required=True)
    uninstall_parser = subparsers.add_parser("uninstall")
    uninstall_parser.add_argument("--target", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify":
            _, report = verify_bundle(Path(args.bundle))
            write_report(report, args.output)
            return 0 if report.passed else 1
        if args.command in {"preflight", "install"}:
            target = Path(args.target)
            manifest, report = preflight(
                Path(args.bundle),
                target,
                web_port=args.web_port,
                minimum_ram_gib=args.minimum_ram_gib,
                minimum_vram_gib=args.minimum_vram_gib,
                disk_reserve_gib=args.disk_reserve_gib,
                check_port=not target.exists(),
            )
            if args.command == "preflight":
                write_report(report, args.output)
                return 0 if report.passed else 1
            if manifest is None or not report.passed:
                write_report(report, None)
                return 1
            install(Path(args.bundle), target, manifest, start=not args.no_start)
            print(f"Installed {manifest['release_id']} at {target}")
            return 0
        if args.command == "backup":
            manifest = create_backup(Path(args.target), Path(args.output))
            print(
                f"Created backup {manifest['backup_id']} at {args.output}; "
                f"payload bytes={manifest['total_size_bytes']}, "
                f"duration seconds={manifest['duration_seconds']}"
            )
            return 0
        if args.command == "backup-verify":
            _, report = verify_backup(Path(args.backup))
            write_report(report, args.output)
            return 0 if report.passed else 1
        if args.command == "restore":
            result = restore_backup(Path(args.backup), Path(args.target))
            print(
                f"Restored {result['backup_id']} into {args.target}; "
                f"migration={result['migration_revision']}, "
                f"duration seconds={result['duration_seconds']}"
            )
            return 0
        uninstall(Path(args.target))
        print(f"Stopped managed installation at {args.target}; data volumes and files were preserved")
        return 0
    except (
        KeyError,
        OSError,
        OperatorError,
        subprocess.TimeoutExpired,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"Offline operator failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
