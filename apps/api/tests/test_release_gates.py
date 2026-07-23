from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

from delivery.release_gates import (
    ALL_REQUIRED_GATES,
    CommandResult,
    CommandSpec,
    REQUIRED_COMMAND_GATES,
    ReleaseGateSpec,
    build_release_decision,
    execute_command,
)


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def create_clean_source(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "source"
    source.mkdir()
    (source / ".dockerignore").write_text("var/\n", encoding="utf-8")
    policy_dir = source / "config" / "supply-chain"
    policy_dir.mkdir(parents=True)
    (policy_dir / "release-source-v1.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "contract_type": "release_source_preflight",
                "required_files": [".dockerignore"],
                "required_dockerignore_patterns": ["var/"],
                "excluded_top_level_paths": [".git", "var"],
                "forbidden_directory_names": ["node_modules"],
                "forbidden_file_suffixes": [".pyc"],
                "forbidden_relative_paths": [],
                "reject_symlinks": True,
            }
        ),
        encoding="utf-8",
    )
    (source / "manage.py").write_text(
        """
from pathlib import Path
import json
import subprocess
import sys

operation = sys.argv[1]
arguments = sys.argv[2:]
revision = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], text=True
).strip()
release_id = "fixture-1.0.0"

def option(name: str) -> Path:
    return Path(arguments[arguments.index(name) + 1])

if operation == "offline-bundle-verify":
    bundle = option("--bundle")
    bundle.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.1",
        "manifest_type": "offline_release_bundle",
        "release_id": release_id,
        "app_version": "1.0.0",
        "target_architecture": "test",
        "source_revision": revision,
        "provenance_spec_path": "provenance/spec.json",
        "provenance_spec_sha256": "0" * 64,
        "provenance_report_path": "provenance/report.json",
        "provenance_report_sha256": "0" * 64,
        "files": [{
            "path": "payload.txt",
            "artifact_type": "application",
            "version": "1",
            "origin": "test",
            "size_bytes": 0,
            "sha256": "0" * 64
        }],
        "total_size_bytes": 0
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    option("--output").write_text("{}")
elif operation == "release-provenance-verify":
    report = {
        "schema_version": "1.0",
        "report_type": "release_artifact_provenance",
        "status": "passed",
        "release_id": release_id,
        "app_version": "1.0.0",
        "target_architecture": "test",
        "source_revision": revision,
        "source_date_epoch": None,
        "source_report_sha256": None,
        "provenance_spec_sha256": "0" * 64,
        "artifacts": [],
        "failures": []
    }
    option("--output").write_text(json.dumps(report))
elif operation == "offline-bundle-signature-verify":
    envelope = {
        "schema_version": "1.0",
        "signature_type": "offline_bundle_detached",
        "algorithm": "Ed25519",
        "key_id": "sha256:" + "0" * 64,
        "payload": {
            "release_id": release_id,
            "manifest_sha256": "0" * 64,
            "manifest_size_bytes": 1,
            "checksums_sha256": "0" * 64,
            "checksums_size_bytes": 1
        },
        "signature_base64": "AA=="
    }
    option("--signature").write_text(json.dumps(envelope))
    option("--public-key").write_text("fixture public key")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    run_git(source, "init", "-q")
    run_git(source, "config", "user.email", "release-gates@example.test")
    run_git(source, "config", "user.name", "Release Gates")
    run_git(source, "add", ".")
    run_git(source, "commit", "-qm", "fixture")
    return source, run_git(source, "rev-parse", "HEAD")


def passing_command() -> dict[str, object]:
    return {
        "argv": ["{python}", "-c", "raise SystemExit(0)"],
        "timeout_seconds": 10,
    }


def build_spec(revision: str) -> ReleaseGateSpec:
    gates: list[dict[str, object]] = []
    for gate_id in REQUIRED_COMMAND_GATES:
        evidence: list[dict[str, object]] = []
        commands: list[dict[str, object]] = [passing_command()]
        if gate_id == "backend_tests":
            commands = [
                {"argv": ["{python}", "manage.py", action], "timeout_seconds": 10}
                for action in ("test", "lint", "typecheck")
            ]
        elif gate_id == "frontend_tests":
            commands = [
                {"argv": prefix, "cwd": "apps/web", "timeout_seconds": 10}
                for prefix in (
                    ["npm", "ci"],
                    ["npm", "run", "test:unit"],
                    ["npm", "run", "typecheck"],
                    ["npm", "run", "build"],
                )
            ]
        elif gate_id == "native_tests":
            commands = [
                {
                    "argv": [
                        "cmake",
                        "-S",
                        "native/vector_similarity",
                        "-B",
                        "{report_dir}/native",
                    ],
                    "timeout_seconds": 10,
                },
                {
                    "argv": ["cmake", "--build", "{report_dir}/native"],
                    "timeout_seconds": 10,
                },
                {
                    "argv": ["ctest", "--test-dir", "{report_dir}/native"],
                    "timeout_seconds": 10,
                },
            ]
        if gate_id == "bundle":
            filename = f"{gate_id}.json"
            commands = [{
                "argv": [
                    "{python}",
                    "manage.py",
                    "offline-bundle-verify",
                    "--bundle",
                    "{source_root}/var/candidate/bundle",
                    "--output",
                    f"{{report_dir}}/{filename}",
                ],
                "timeout_seconds": 10,
            }]
            evidence = [
                {
                    "evidence_id": f"{gate_id}_evidence",
                    "path": f"{{report_dir}}/{filename}",
                    "fresh": True,
                }
            ]
        elif gate_id == "sbom":
            filename = f"{gate_id}.json"
            commands = [{
                "argv": [
                    "{python}",
                    "manage.py",
                    "release-provenance-verify",
                    "--spec",
                    "{source_root}/var/candidate/bundle/provenance/spec.json",
                    "--output",
                    f"{{report_dir}}/{filename}",
                ],
                "timeout_seconds": 10,
            }]
            evidence = [
                {
                    "evidence_id": "sbom_evidence",
                    "path": f"{{report_dir}}/{filename}",
                    "fresh": True,
                }
            ]
        elif gate_id == "signature":
            commands = [{
                "argv": [
                    "{python}",
                    "manage.py",
                    "offline-bundle-signature-verify",
                    "--bundle",
                    "{source_root}/var/candidate/bundle",
                    "--signature",
                    "{report_dir}/release.signature.json",
                    "--public-key",
                    "{report_dir}/release-public.pem",
                ],
                "timeout_seconds": 10,
            }]
            evidence = [
                {
                    "evidence_id": "detached_signature",
                    "path": "{report_dir}/release.signature.json",
                    "fresh": True,
                },
                {
                    "evidence_id": "external_public_key",
                    "path": "{report_dir}/release-public.pem",
                    "fresh": True,
                },
            ]
        elif gate_id == "container_policy":
            commands = [
                {
                    "argv": [
                        "env",
                        "{python}",
                        "-m",
                        "pytest",
                        "apps/api/tests/test_production_compose_hardening.py",
                    ],
                    "timeout_seconds": 10,
                },
                {
                    "argv": ["docker", "compose", "config", "--quiet"],
                    "timeout_seconds": 10,
                },
                {
                    "argv": [
                        "{python}",
                        "manage.py",
                        "release-trust-policy-verify",
                    ],
                    "timeout_seconds": 10,
                },
            ]
        gates.append(
            {
                "gate_id": gate_id,
                "commands": commands,
                "evidence": evidence,
            }
        )
    return ReleaseGateSpec.model_validate(
        {
            "schema_version": "1.0",
            "spec_type": "offline_release_gate_spec",
            "release_id": "fixture-1.0.0",
            "expected_revision": revision,
            "source_policy": "config/supply-chain/release-source-v1.json",
            "gates": gates,
        }
    )


def fake_execute_command(
    command: CommandSpec,
    **kwargs: object,
) -> CommandResult:
    if command.argv[:1] == ["{python}"]:
        return execute_command(command, **kwargs)  # type: ignore[arg-type]
    empty_digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    return CommandResult(
        command_index=int(kwargs["command_index"]),
        status="passed",
        exit_code=0,
        duration_ms=0,
        stdout_bytes=0,
        stdout_sha256=empty_digest,
        stderr_bytes=0,
        stderr_sha256=empty_digest,
    )


def run_decision(tmp_path: Path, spec: ReleaseGateSpec, source: Path):
    reports = tmp_path / "reports"
    return build_release_decision(
        spec,
        source_root=source,
        report_dir=reports,
        log_path=reports / "release-gates.jsonl",
        executor=fake_execute_command,
    )


def test_release_decision_passes_only_when_every_gate_passes(tmp_path: Path) -> None:
    source, revision = create_clean_source(tmp_path)

    decision = run_decision(tmp_path, build_spec(revision), source)

    assert decision.decision == "pass"
    assert [gate.gate_id for gate in decision.gates] == list(ALL_REQUIRED_GATES)
    assert all(gate.status == "passed" for gate in decision.gates)
    assert decision.failures == []


def test_release_gate_spec_rejects_a_missing_mandatory_gate(tmp_path: Path) -> None:
    _, revision = create_clean_source(tmp_path)
    payload = build_spec(revision).model_dump(mode="json")
    payload["gates"] = payload["gates"][:-1]

    with pytest.raises(ValidationError, match="release gates must be exact"):
        ReleaseGateSpec.model_validate(payload)


def test_release_gate_spec_rejects_a_semantically_skipped_check(
    tmp_path: Path,
) -> None:
    _, revision = create_clean_source(tmp_path)
    payload = build_spec(revision).model_dump(mode="json")
    backend = next(
        gate for gate in payload["gates"] if gate["gate_id"] == "backend_tests"
    )
    backend["commands"] = [
        command
        for command in backend["commands"]
        if command["argv"][:3] != ["{python}", "manage.py", "typecheck"]
    ]

    with pytest.raises(ValidationError, match="missing mandatory command"):
        ReleaseGateSpec.model_validate(payload)


def test_failed_command_blocks_every_later_gate(tmp_path: Path) -> None:
    source, revision = create_clean_source(tmp_path)
    spec = build_spec(revision)
    backend = next(gate for gate in spec.gates if gate.gate_id == "backend_tests")
    backend.commands[0].argv = ["{python}", "-c", "raise SystemExit(7)"]

    decision = run_decision(tmp_path, spec, source)

    assert decision.decision == "fail"
    assert decision.gates[1].status == "failed"
    assert all(gate.status == "not_run" for gate in decision.gates[2:])


def test_missing_declared_evidence_fails_closed(tmp_path: Path) -> None:
    source, revision = create_clean_source(tmp_path)
    spec = build_spec(revision)
    bundle = next(gate for gate in spec.gates if gate.gate_id == "bundle")
    bundle.commands = [CommandSpec.model_validate(passing_command())]

    decision = run_decision(tmp_path, spec, source)

    bundle_result = next(gate for gate in decision.gates if gate.gate_id == "bundle")
    assert decision.decision == "fail"
    assert bundle_result.status == "failed"
    assert bundle_result.failures == ["required evidence is missing: bundle_evidence"]


def test_dirty_source_blocks_commands_before_execution(tmp_path: Path) -> None:
    source, revision = create_clean_source(tmp_path)
    (source / "uncommitted.txt").write_text("dirty", encoding="utf-8")

    decision = run_decision(tmp_path, build_spec(revision), source)

    assert decision.decision == "fail"
    assert decision.gates[0].status == "failed"
    assert all(gate.status == "not_run" for gate in decision.gates[1:])


def test_candidate_release_identity_must_match_the_gate_spec(tmp_path: Path) -> None:
    source, revision = create_clean_source(tmp_path)
    spec = build_spec(revision)
    spec.release_id = "different-release-1.0.0"

    decision = run_decision(tmp_path, spec, source)

    bundle = next(gate for gate in decision.gates if gate.gate_id == "bundle")
    assert decision.decision == "fail"
    assert bundle.status == "failed"
    assert bundle.failures == [
        "candidate release ID does not match release gate specification"
    ]


def test_metadata_log_does_not_retain_child_output_or_sensitive_arguments(
    tmp_path: Path,
) -> None:
    source, revision = create_clean_source(tmp_path)
    spec = build_spec(revision)
    backend = next(gate for gate in spec.gates if gate.gate_id == "backend_tests")
    backend.commands[0].argv = [
        "{python}",
        "-c",
        "print('private document text and bearer credential')",
        "--token",
        "top-secret-value",
    ]

    decision = run_decision(tmp_path, spec, source)
    log_text = Path(decision.log_path).read_text(encoding="utf-8")
    report_text = decision.model_dump_json()

    assert decision.decision == "pass"
    assert "private document text" not in log_text
    assert "bearer credential" not in log_text
    assert "top-secret-value" not in log_text
    assert "top-secret-value" not in report_text
    assert "[REDACTED]" in log_text


def test_cleanup_runs_after_a_gate_command_failure(tmp_path: Path) -> None:
    source, revision = create_clean_source(tmp_path)
    spec = build_spec(revision)
    marker = tmp_path / "cleanup-ran"
    backend = next(gate for gate in spec.gates if gate.gate_id == "backend_tests")
    backend.commands[0].argv = ["{python}", "-c", "raise SystemExit(1)"]
    backend.cleanup_commands = [
        backend.commands[0].model_copy(
            update={
                "argv": [
                    "{python}",
                    "-c",
                    f"from pathlib import Path; Path(r'{marker}').touch()",
                ]
            }
        )
    ]

    decision = run_decision(tmp_path, spec, source)

    assert decision.decision == "fail"
    assert marker.is_file()
    assert decision.gates[1].cleanup_commands[0].status == "passed"
