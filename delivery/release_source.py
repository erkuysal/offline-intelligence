from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
REVISION_PATTERN = re.compile(r"^[a-f0-9]{40}$")


class ReleaseSourceError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"path must be a normalized relative POSIX path: {value!r}")
    if "\\" in value:
        raise ValueError(f"path must use POSIX separators: {value!r}")


class ReleaseSourceContract(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    contract_type: Literal["release_source_preflight"] = "release_source_preflight"
    required_files: list[str] = Field(min_length=1)
    required_dockerignore_patterns: list[str] = Field(min_length=1)
    excluded_top_level_paths: list[str] = Field(min_length=1)
    forbidden_directory_names: list[str] = Field(min_length=1)
    forbidden_file_suffixes: list[str] = Field(min_length=1)
    forbidden_relative_paths: list[str] = Field(default_factory=list)
    reject_symlinks: bool = True

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        for value in self.required_files + self.forbidden_relative_paths:
            validate_relative_path(value)
        for value in self.excluded_top_level_paths + self.forbidden_directory_names:
            if not value or "/" in value or "\\" in value or value in {".", ".."}:
                raise ValueError(f"directory name must be one normalized path component: {value!r}")
        for value in self.forbidden_file_suffixes:
            if not value.startswith(".") or "/" in value or "\\" in value:
                raise ValueError(f"forbidden suffix must start with a dot: {value!r}")
        collections = (
            self.required_files,
            self.required_dockerignore_patterns,
            self.excluded_top_level_paths,
            self.forbidden_directory_names,
            self.forbidden_file_suffixes,
            self.forbidden_relative_paths,
        )
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("release source contract lists must not contain duplicates")
        return self


class RequiredFileRecord(StrictModel):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)


class ReleaseSourceReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    report_type: Literal["release_source_preflight"] = "release_source_preflight"
    status: Literal["passed", "failed"]
    source_root: str
    source_revision: str | None
    expected_revision: str
    source_date_epoch: int | None
    git_tree_clean: bool
    git_status_entries: list[str]
    required_files: list[RequiredFileRecord]
    forbidden_context_paths: list[str]
    missing_dockerignore_patterns: list[str]
    failures: list[str]

    @property
    def passed(self) -> bool:
        return not self.failures


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_release_source_contract(path: Path) -> ReleaseSourceContract:
    return ReleaseSourceContract.model_validate_json(path.read_text(encoding="utf-8"))


def run_git(source_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=source_root,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise ReleaseSourceError(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout.strip()


def find_forbidden_context_paths(
    source_root: Path,
    contract: ReleaseSourceContract,
) -> list[str]:
    findings: set[str] = set()
    forbidden_paths = set(contract.forbidden_relative_paths)
    forbidden_directories = set(contract.forbidden_directory_names)
    excluded_top_level = set(contract.excluded_top_level_paths)

    for current, directories, filenames in os.walk(source_root, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_current = current_path.relative_to(source_root)
        if relative_current == Path("."):
            directories[:] = [name for name in directories if name not in excluded_top_level]

        retained_directories: list[str] = []
        for name in directories:
            path = current_path / name
            relative = path.relative_to(source_root).as_posix()
            if name in forbidden_directories or relative in forbidden_paths:
                findings.add(relative)
                continue
            if contract.reject_symlinks and path.is_symlink():
                findings.add(relative)
                continue
            retained_directories.append(name)
        directories[:] = retained_directories

        for name in filenames:
            path = current_path / name
            relative = path.relative_to(source_root).as_posix()
            if relative in forbidden_paths or any(
                name.endswith(suffix) for suffix in contract.forbidden_file_suffixes
            ):
                findings.add(relative)
            elif contract.reject_symlinks and path.is_symlink():
                findings.add(relative)

    return sorted(findings)


def build_release_source_report(
    contract: ReleaseSourceContract,
    *,
    source_root: Path,
    expected_revision: str,
) -> ReleaseSourceReport:
    if not REVISION_PATTERN.fullmatch(expected_revision):
        raise ReleaseSourceError("expected revision must be a full lowercase 40-character Git SHA")

    source_root = source_root.expanduser().resolve()
    if not source_root.is_dir():
        raise ReleaseSourceError(f"source root is not a directory: {source_root}")
    repository_root = Path(run_git(source_root, "rev-parse", "--show-toplevel")).resolve()
    if repository_root != source_root:
        raise ReleaseSourceError(
            f"source root must be the Git repository root: expected {repository_root}, found {source_root}"
        )

    source_revision = run_git(source_root, "rev-parse", "HEAD")
    source_date_epoch_text = run_git(source_root, "show", "-s", "--format=%ct", "HEAD")
    source_date_epoch = int(source_date_epoch_text)
    status_output = run_git(source_root, "status", "--porcelain=v1", "--untracked-files=all")
    status_entries = sorted(line for line in status_output.splitlines() if line)
    failures: list[str] = []
    if source_revision != expected_revision:
        failures.append(
            f"source revision mismatch: expected {expected_revision}, found {source_revision}"
        )
    if status_entries:
        failures.append("Git source tree is not clean")

    required_files: list[RequiredFileRecord] = []
    for relative in sorted(contract.required_files):
        path = source_root.joinpath(*PurePosixPath(relative).parts)
        if path.is_symlink() or not path.is_file():
            failures.append(f"required source file is missing or not a regular file: {relative}")
            continue
        required_files.append(
            RequiredFileRecord(
                path=relative,
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
            )
        )

    dockerignore = source_root / ".dockerignore"
    dockerignore_lines = {
        line.strip()
        for line in dockerignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    } if dockerignore.is_file() else set()
    missing_patterns = sorted(
        set(contract.required_dockerignore_patterns) - dockerignore_lines
    )
    failures.extend(
        f"required .dockerignore pattern is missing: {pattern}" for pattern in missing_patterns
    )

    forbidden_paths = find_forbidden_context_paths(source_root, contract)
    failures.extend(f"forbidden build-context path: {path}" for path in forbidden_paths)

    return ReleaseSourceReport(
        status="failed" if failures else "passed",
        source_root=str(source_root),
        source_revision=source_revision,
        expected_revision=expected_revision,
        source_date_epoch=source_date_epoch,
        git_tree_clean=not status_entries,
        git_status_entries=status_entries,
        required_files=required_files,
        forbidden_context_paths=forbidden_paths,
        missing_dockerignore_patterns=missing_patterns,
        failures=failures,
    )


def write_release_source_report(report: ReleaseSourceReport, output: Path) -> None:
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    output.write_text(payload, encoding="utf-8")


def format_release_source_summary(report: ReleaseSourceReport) -> str:
    lines = [
        f"Release source preflight: {'PASS' if report.passed else 'FAIL'}",
        f"Revision: {report.source_revision or 'unavailable'}",
        f"Required files: {len(report.required_files)}",
        f"Forbidden context paths: {len(report.forbidden_context_paths)}",
    ]
    lines.extend(f"- {failure}" for failure in report.failures[:10])
    return "\n".join(lines)
