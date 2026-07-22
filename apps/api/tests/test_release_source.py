from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

import pytest

import manage
from delivery.release_source import ReleaseSourceContract, build_release_source_report


def run_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def write_repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "source"
    root.mkdir()
    run_git(root, "init", "--quiet")
    run_git(root, "config", "user.name", "Release Test")
    run_git(root, "config", "user.email", "release-test@example.invalid")
    (root / ".dockerignore").write_text("**/__pycache__/\n**/*.py[cod]\n", encoding="utf-8")
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\nvar/\n", encoding="utf-8")
    (root / "required.txt").write_text("pinned\n", encoding="utf-8")
    run_git(root, "add", ".dockerignore", ".gitignore", "required.txt")
    run_git(root, "commit", "--quiet", "-m", "test source")
    return root, run_git(root, "rev-parse", "HEAD")


def source_contract() -> ReleaseSourceContract:
    return ReleaseSourceContract(
        required_files=[".dockerignore", "required.txt"],
        required_dockerignore_patterns=["**/__pycache__/", "**/*.py[cod]"],
        excluded_top_level_paths=[".git", "var"],
        forbidden_directory_names=["__pycache__", "node_modules"],
        forbidden_file_suffixes=[".pyc", ".pyo"],
        forbidden_relative_paths=["config/env/prod.env"],
    )


def test_clean_committed_source_passes_and_records_stable_inputs(tmp_path: Path) -> None:
    root, revision = write_repository(tmp_path)

    report = build_release_source_report(
        source_contract(),
        source_root=root,
        expected_revision=revision,
    )

    assert report.passed is True
    assert report.git_tree_clean is True
    assert report.source_revision == revision
    assert report.source_date_epoch is not None
    assert [record.path for record in report.required_files] == [
        ".dockerignore",
        "required.txt",
    ]


def test_source_revision_and_dirty_tree_fail_closed(tmp_path: Path) -> None:
    root, revision = write_repository(tmp_path)
    (root / "required.txt").write_text("changed\n", encoding="utf-8")

    report = build_release_source_report(
        source_contract(),
        source_root=root,
        expected_revision="0" * 40,
    )

    assert report.passed is False
    assert report.git_tree_clean is False
    assert any("source revision mismatch" in failure for failure in report.failures)
    assert "Git source tree is not clean" in report.failures
    assert report.source_revision == revision


def test_ignored_nested_bytecode_is_still_rejected(tmp_path: Path) -> None:
    root, revision = write_repository(tmp_path)
    cache = root / "apps" / "api" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "config.cpython-314.pyc").write_bytes(b"generated")

    report = build_release_source_report(
        source_contract(),
        source_root=root,
        expected_revision=revision,
    )

    assert report.git_tree_clean is True
    assert report.passed is False
    assert report.forbidden_context_paths == ["apps/api/__pycache__"]
    assert any("forbidden build-context path" in failure for failure in report.failures)


def test_missing_required_dockerignore_pattern_is_rejected(tmp_path: Path) -> None:
    root, revision = write_repository(tmp_path)
    (root / ".dockerignore").write_text("**/__pycache__/\n", encoding="utf-8")
    run_git(root, "add", ".dockerignore")
    run_git(root, "commit", "--quiet", "-m", "remove required ignore")
    revision = run_git(root, "rev-parse", "HEAD")

    report = build_release_source_report(
        source_contract(),
        source_root=root,
        expected_revision=revision,
    )

    assert report.passed is False
    assert report.missing_dockerignore_patterns == ["**/*.py[cod]"]


def test_cli_writes_machine_readable_failed_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, revision = write_repository(tmp_path)
    cache = root / "nested" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "module.pyc").write_bytes(b"generated")
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(source_contract().model_dump_json(), encoding="utf-8")
    output = root / "var" / "source-report.json"
    monkeypatch.setattr(sys, "dont_write_bytecode", False)

    status = manage.release_source_verify(
        argparse.Namespace(
            contract=str(contract_path),
            source=str(root),
            expected_revision=revision,
            output=str(output),
        )
    )

    assert status == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["forbidden_context_paths"] == ["nested/__pycache__"]
    assert sys.dont_write_bytecode is True


def test_git_commands_do_not_depend_on_callers_locale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, revision = write_repository(tmp_path)
    monkeypatch.setenv("LC_ALL", "tr_TR.UTF-8")

    report = build_release_source_report(
        source_contract(),
        source_root=root,
        expected_revision=revision,
    )

    assert report.passed is True
