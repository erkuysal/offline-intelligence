from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
from time import monotonic_ns
from typing import Callable, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from delivery.release_source import (
    ReleaseSourceError,
    build_release_source_report,
    load_release_source_contract,
    write_release_source_report,
)


REQUIRED_COMMAND_GATES = (
    "backend_tests",
    "frontend_tests",
    "native_tests",
    "bundle",
    "sbom",
    "signature",
    "container_policy",
)
ALL_REQUIRED_GATES = ("source", *REQUIRED_COMMAND_GATES)
EVIDENCE_GATES = {"bundle", "sbom", "signature"}
SENSITIVE_ARGUMENT_MARKERS = (
    "authorization",
    "bearer",
    "database_url",
    "dsn",
    "password",
    "private-key",
    "prompt",
    "redis_url",
    "secret",
    "token",
)
PLACEHOLDERS = {"{python}", "{report_dir}", "{source_root}"}


class ReleaseGateError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def validate_relative_path(value: str, *, field_name: str) -> None:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in value
    ):
        raise ValueError(f"{field_name} must be a normalized relative POSIX path")


class CommandSpec(StrictModel):
    argv: list[str] = Field(min_length=1)
    cwd: str = "."
    timeout_seconds: int = Field(default=900, ge=1, le=7200)

    @model_validator(mode="after")
    def validate_command(self) -> Self:
        if self.cwd != ".":
            validate_relative_path(self.cwd, field_name="command cwd")
        for argument in self.argv:
            if not argument or "\x00" in argument:
                raise ValueError("command arguments must be non-empty and must not contain NUL")
        return self


class EvidenceSpec(StrictModel):
    evidence_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    path: str = Field(min_length=1)
    fresh: bool = True


class CommandGateSpec(StrictModel):
    gate_id: Literal[
        "backend_tests",
        "frontend_tests",
        "native_tests",
        "bundle",
        "sbom",
        "signature",
        "container_policy",
    ]
    commands: list[CommandSpec] = Field(min_length=1)
    cleanup_commands: list[CommandSpec] = Field(default_factory=list)
    evidence: list[EvidenceSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("gate evidence IDs must be unique")
        if self.gate_id in EVIDENCE_GATES and not self.evidence:
            raise ValueError(f"{self.gate_id} gate must declare evidence")
        command_lines = [command.argv for command in self.commands]

        def require_prefix(prefix: list[str]) -> None:
            if not any(argv[: len(prefix)] == prefix for argv in command_lines):
                raise ValueError(
                    f"{self.gate_id} gate is missing mandatory command: {' '.join(prefix)}"
                )

        if self.gate_id == "backend_tests":
            for action in ("test", "lint", "typecheck"):
                require_prefix(["{python}", "manage.py", action])
        elif self.gate_id == "frontend_tests":
            for prefix in (
                ["npm", "ci"],
                ["npm", "run", "test:unit"],
                ["npm", "run", "typecheck"],
                ["npm", "run", "build"],
            ):
                require_prefix(prefix)
        elif self.gate_id == "native_tests":
            for prefix in (
                ["cmake", "-S", "native/vector_similarity"],
                ["cmake", "--build"],
                ["ctest", "--test-dir"],
            ):
                require_prefix(prefix)
        elif self.gate_id == "bundle":
            require_prefix(["{python}", "manage.py", "offline-bundle-verify"])
        elif self.gate_id == "sbom":
            require_prefix(["{python}", "manage.py", "release-provenance-verify"])
        elif self.gate_id == "signature":
            require_prefix(
                ["{python}", "manage.py", "offline-bundle-signature-verify"]
            )
        elif self.gate_id == "container_policy":
            require_prefix(["{python}", "manage.py", "release-trust-policy-verify"])
            if not any(
                "apps/api/tests/test_production_compose_hardening.py" in argv
                and "pytest" in argv
                for argv in command_lines
            ):
                raise ValueError(
                    "container_policy gate must run the production Compose hardening tests"
                )
            if not any(
                "docker" in argv and "compose" in argv and "config" in argv
                for argv in command_lines
            ):
                raise ValueError(
                    "container_policy gate must validate the production Compose model"
                )
        return self


class ReleaseGateSpec(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    spec_type: Literal["offline_release_gate_spec"] = "offline_release_gate_spec"
    release_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    expected_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    source_policy: str = "config/supply-chain/release-source-v1.json"
    gates: list[CommandGateSpec]

    @model_validator(mode="after")
    def validate_gate_set(self) -> Self:
        validate_relative_path(self.source_policy, field_name="source policy")
        gate_ids = [gate.gate_id for gate in self.gates]
        if len(gate_ids) != len(set(gate_ids)):
            raise ValueError("release gate IDs must be unique")
        if set(gate_ids) != set(REQUIRED_COMMAND_GATES):
            missing = sorted(set(REQUIRED_COMMAND_GATES) - set(gate_ids))
            unexpected = sorted(set(gate_ids) - set(REQUIRED_COMMAND_GATES))
            raise ValueError(
                f"release gates must be exact; missing={missing}, unexpected={unexpected}"
            )
        return self


class CommandResult(StrictModel):
    command_index: int = Field(ge=1)
    status: Literal["passed", "failed", "timed_out"]
    exit_code: int | None
    duration_ms: int = Field(ge=0)
    stdout_bytes: int = Field(ge=0)
    stdout_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    stderr_bytes: int = Field(ge=0)
    stderr_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class EvidenceRecord(StrictModel):
    evidence_id: str
    path: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    fresh: bool


class GateResult(StrictModel):
    gate_id: str
    status: Literal["passed", "failed", "not_run"]
    commands: list[CommandResult] = Field(default_factory=list)
    cleanup_commands: list[CommandResult] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class ReleaseDecision(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    report_type: Literal["offline_release_decision"] = "offline_release_decision"
    release_id: str
    expected_revision: str
    source_revision: str | None
    decision: Literal["pass", "fail"]
    gates: list[GateResult]
    failures: list[str]
    log_path: str


def load_release_gate_spec(path: Path) -> ReleaseGateSpec:
    return ReleaseGateSpec.model_validate_json(path.read_text(encoding="utf-8"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_placeholders(value: str, *, source_root: Path, report_dir: Path) -> str:
    replacements = {
        "{python}": sys.executable,
        "{report_dir}": str(report_dir),
        "{source_root}": str(source_root),
    }
    result = value
    for placeholder, replacement in replacements.items():
        result = result.replace(placeholder, replacement)
    unresolved = [item for item in PLACEHOLDERS if item in result]
    if unresolved:
        raise ReleaseGateError(f"unresolved command placeholder: {unresolved[0]}")
    return result


def resolve_evidence_path(value: str, *, source_root: Path, report_dir: Path) -> Path:
    resolved = Path(
        resolve_placeholders(value, source_root=source_root, report_dir=report_dir)
    ).expanduser()
    if not resolved.is_absolute():
        resolved = source_root / resolved
    return resolved


def safe_command_shape(argv: list[str]) -> list[str]:
    safe: list[str] = []
    redact_next = False
    for argument in argv:
        lowered = argument.lower()
        if redact_next:
            safe.append("[REDACTED]")
            redact_next = False
            continue
        if argument in {"-c", "-e", "--eval", "-Command"}:
            safe.append(argument)
            redact_next = True
            continue
        if "://" in argument and "@" in argument:
            safe.append("[REDACTED_URL]")
            continue
        if any(marker in lowered for marker in SENSITIVE_ARGUMENT_MARKERS):
            if "=" in argument:
                safe.append(f"{argument.split('=', maxsplit=1)[0]}=[REDACTED]")
            elif argument.startswith("-"):
                safe.append(argument)
                redact_next = True
            else:
                safe.append("[REDACTED]")
            continue
        safe.append(argument)
    return safe


def write_log_event(log_path: Path, payload: dict[str, object]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def command_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "EMBEDDING_BACKEND": "fake",
            "EMBEDDING_MODEL": "fake-bow",
            "LLM_BACKEND": "fake",
            "LLM_WARMUP_ENABLED": "false",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def execute_command(
    command: CommandSpec,
    *,
    command_index: int,
    source_root: Path,
    report_dir: Path,
    log_path: Path,
    phase: Literal["gate", "cleanup"],
) -> CommandResult:
    argv = [
        resolve_placeholders(item, source_root=source_root, report_dir=report_dir)
        for item in command.argv
    ]
    cwd = source_root if command.cwd == "." else source_root / command.cwd
    if not cwd.is_dir():
        raise ReleaseGateError(f"command cwd does not exist: {command.cwd}")
    write_log_event(
        log_path,
        {
            "event": "command_started",
            "phase": phase,
            "command_index": command_index,
            "argv": safe_command_shape(argv),
            "cwd": command.cwd,
        },
    )
    started = monotonic_ns()
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=command_environment(),
            capture_output=True,
            check=False,
            timeout=command.timeout_seconds,
        )
        status: Literal["passed", "failed", "timed_out"] = (
            "passed" if completed.returncode == 0 else "failed"
        )
        exit_code: int | None = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        status = "timed_out"
        exit_code = None
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
    duration_ms = max(0, (monotonic_ns() - started) // 1_000_000)
    result = CommandResult(
        command_index=command_index,
        status=status,
        exit_code=exit_code,
        duration_ms=duration_ms,
        stdout_bytes=len(stdout),
        stdout_sha256=sha256_bytes(stdout),
        stderr_bytes=len(stderr),
        stderr_sha256=sha256_bytes(stderr),
    )
    write_log_event(
        log_path,
        {
            "event": "command_finished",
            "phase": phase,
            **result.model_dump(mode="json"),
        },
    )
    return result


def evidence_state(path: Path) -> tuple[int, int, str] | None:
    if path.is_symlink() or not path.is_file():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size, sha256_file(path)


def run_command_gate(
    gate: CommandGateSpec,
    *,
    source_root: Path,
    report_dir: Path,
    log_path: Path,
    executor: Callable[..., CommandResult] = execute_command,
) -> GateResult:
    before = {
        item.evidence_id: evidence_state(
            resolve_evidence_path(item.path, source_root=source_root, report_dir=report_dir)
        )
        for item in gate.evidence
    }
    commands: list[CommandResult] = []
    cleanup_commands: list[CommandResult] = []
    failures: list[str] = []
    for index, command in enumerate(gate.commands, start=1):
        try:
            result = executor(
                command,
                command_index=index,
                source_root=source_root,
                report_dir=report_dir,
                log_path=log_path,
                phase="gate",
            )
        except (OSError, ReleaseGateError) as exc:
            failures.append(f"command {index} could not start: {type(exc).__name__}")
            break
        commands.append(result)
        if result.status != "passed":
            failures.append(f"command {index} {result.status}")
            break

    for index, command in enumerate(gate.cleanup_commands, start=1):
        try:
            result = executor(
                command,
                command_index=index,
                source_root=source_root,
                report_dir=report_dir,
                log_path=log_path,
                phase="cleanup",
            )
        except (OSError, ReleaseGateError) as exc:
            failures.append(f"cleanup command {index} could not start: {type(exc).__name__}")
            continue
        cleanup_commands.append(result)
        if result.status != "passed":
            failures.append(f"cleanup command {index} {result.status}")

    evidence: list[EvidenceRecord] = []
    if not failures:
        for declared in gate.evidence:
            path = resolve_evidence_path(
                declared.path,
                source_root=source_root,
                report_dir=report_dir,
            )
            state = evidence_state(path)
            if state is None:
                failures.append(f"required evidence is missing: {declared.evidence_id}")
                continue
            mtime_ns, size_bytes, digest = state
            previous_state = before[declared.evidence_id]
            if declared.fresh and previous_state is not None:
                before_mtime_ns = previous_state[0]
                if mtime_ns <= before_mtime_ns:
                    failures.append(
                        f"required evidence was not refreshed: {declared.evidence_id}"
                    )
                    continue
            evidence.append(
                EvidenceRecord(
                    evidence_id=declared.evidence_id,
                    path=declared.path,
                    size_bytes=size_bytes,
                    sha256=digest,
                    fresh=declared.fresh,
                )
            )

    return GateResult(
        gate_id=gate.gate_id,
        status="failed" if failures else "passed",
        commands=commands,
        cleanup_commands=cleanup_commands,
        evidence=evidence,
        failures=failures,
    )


def command_option(
    gate: CommandGateSpec,
    command_name: str,
    option: str,
    *,
    source_root: Path,
    report_dir: Path,
) -> str:
    for command in gate.commands:
        argv = [
            resolve_placeholders(item, source_root=source_root, report_dir=report_dir)
            for item in command.argv
        ]
        if command_name not in argv:
            continue
        try:
            value = argv[argv.index(option) + 1]
        except (ValueError, IndexError) as exc:
            raise ReleaseGateError(
                f"{command_name} command must provide {option}"
            ) from exc
        return value
    raise ReleaseGateError(f"{command_name} command is mandatory")


def validate_candidate_identity(
    gate: CommandGateSpec,
    result: GateResult,
    *,
    release_id: str,
    expected_revision: str,
    source_root: Path,
    report_dir: Path,
) -> None:
    if result.status != "passed":
        return
    try:
        if gate.gate_id == "bundle":
            from delivery.offline_bundle import load_bundle_manifest

            bundle = Path(
                command_option(
                    gate,
                    "offline-bundle-verify",
                    "--bundle",
                    source_root=source_root,
                    report_dir=report_dir,
                )
            )
            manifest = load_bundle_manifest(bundle / "manifest.json")
            candidate_release_id = manifest.release_id
            candidate_revision = manifest.source_revision
        elif gate.gate_id == "sbom":
            from delivery.release_provenance import ReleaseProvenanceReport

            evidence_path = resolve_evidence_path(
                gate.evidence[0].path,
                source_root=source_root,
                report_dir=report_dir,
            )
            report = ReleaseProvenanceReport.model_validate_json(
                evidence_path.read_text(encoding="utf-8")
            )
            if not report.passed:
                raise ReleaseGateError("provenance report did not pass")
            candidate_release_id = report.release_id
            candidate_revision = report.source_revision
        elif gate.gate_id == "signature":
            from delivery.release_signing import SignatureEnvelope

            signature = Path(
                command_option(
                    gate,
                    "offline-bundle-signature-verify",
                    "--signature",
                    source_root=source_root,
                    report_dir=report_dir,
                )
            )
            envelope = SignatureEnvelope.model_validate_json(
                signature.read_text(encoding="utf-8")
            )
            candidate_release_id = envelope.payload.release_id
            candidate_revision = expected_revision
        else:
            return
    except (OSError, ReleaseGateError, ValueError) as exc:
        result.status = "failed"
        result.failures.append(
            f"candidate identity validation failed: {type(exc).__name__}"
        )
        return

    if candidate_release_id != release_id:
        result.failures.append("candidate release ID does not match release gate specification")
    if candidate_revision != expected_revision:
        result.failures.append("candidate source revision does not match release gate specification")
    if result.failures:
        result.status = "failed"


def build_release_decision(
    spec: ReleaseGateSpec,
    *,
    source_root: Path,
    report_dir: Path,
    log_path: Path,
    executor: Callable[..., CommandResult] = execute_command,
) -> ReleaseDecision:
    source_root = source_root.expanduser().resolve()
    report_dir = report_dir.expanduser().resolve()
    log_path = log_path.expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        log_path.unlink()

    source_report_path = report_dir / "source-preflight.json"
    try:
        contract = load_release_source_contract(source_root / spec.source_policy)
        source_report = build_release_source_report(
            contract,
            source_root=source_root,
            expected_revision=spec.expected_revision,
        )
        write_release_source_report(source_report, source_report_path)
        source_failures = list(source_report.failures)
        source_revision = source_report.source_revision
    except (OSError, ReleaseSourceError, ValueError) as exc:
        source_failures = [f"source gate could not run: {type(exc).__name__}"]
        source_revision = None
    source_gate = GateResult(
        gate_id="source",
        status="failed" if source_failures else "passed",
        evidence=(
            [
                EvidenceRecord(
                    evidence_id="source_preflight",
                    path=str(source_report_path),
                    size_bytes=source_report_path.stat().st_size,
                    sha256=sha256_file(source_report_path),
                    fresh=True,
                )
            ]
            if source_report_path.is_file()
            else []
        ),
        failures=source_failures,
    )
    results = [source_gate]

    ordered_gates: dict[str, CommandGateSpec] = {
        gate.gate_id: gate for gate in spec.gates
    }
    blocked = bool(source_failures)
    for gate_id in REQUIRED_COMMAND_GATES:
        gate = ordered_gates[gate_id]
        if blocked:
            results.append(
                GateResult(
                    gate_id=gate_id,
                    status="not_run",
                    failures=["blocked by an earlier mandatory gate"],
                )
            )
            continue
        result = run_command_gate(
            gate,
            source_root=source_root,
            report_dir=report_dir,
            log_path=log_path,
            executor=executor,
        )
        validate_candidate_identity(
            gate,
            result,
            release_id=spec.release_id,
            expected_revision=spec.expected_revision,
            source_root=source_root,
            report_dir=report_dir,
        )
        results.append(result)
        blocked = result.status != "passed"

    failures = [
        f"{result.gate_id}: {failure}"
        for result in results
        for failure in result.failures
    ]
    if [result.gate_id for result in results] != list(ALL_REQUIRED_GATES):
        failures.append("release decision does not contain every mandatory gate")
    if any(result.status != "passed" for result in results):
        failures.append("one or more mandatory release gates did not pass")
    return ReleaseDecision(
        release_id=spec.release_id,
        expected_revision=spec.expected_revision,
        source_revision=source_revision,
        decision="fail" if failures else "pass",
        gates=results,
        failures=failures,
        log_path=str(log_path),
    )


def write_release_decision(decision: ReleaseDecision, output: Path) -> None:
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(decision.model_dump_json(indent=2) + "\n", encoding="utf-8")
