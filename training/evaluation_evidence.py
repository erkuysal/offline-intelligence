from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


RUNTIME_MODES = {"base", "base_rag", "adapter", "adapter_rag"}


class EvidenceArtifact(BaseModel):
    report_type: Literal[
        "dataset_validation",
        "training_run",
        "held_out_behavior_matrix",
        "production_runtime_evaluation",
    ]
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluation_mode: str | None = None
    evaluation_scope: Literal["behavior", "regression"] | None = None


class EvaluationEvidenceIndex(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    report_type: Literal["phase_5_evidence_index"] = "phase_5_evidence_index"
    generated_at: datetime
    training_dataset_id: str
    training_dataset_version: str
    training_dataset_checksum: str
    evaluation_dataset_id: str
    evaluation_dataset_version: str
    regression_dataset_id: str
    regression_dataset_version: str
    adapter_id: str
    artifacts: list[EvidenceArtifact]


def build_evaluation_evidence_index(
    *,
    dataset_validation_path: Path,
    training_run_path: Path,
    held_out_behavior_path: Path,
    runtime_paths: Sequence[Path],
    regression_runtime_paths: Sequence[Path],
) -> EvaluationEvidenceIndex:
    validation = load_typed_report(dataset_validation_path, "dataset_validation")
    training = load_typed_report(training_run_path, "training_run")
    held_out = load_typed_report(held_out_behavior_path, "held_out_behavior_matrix")
    runtimes = [
        (path, load_typed_report(path, "production_runtime_evaluation"))
        for path in runtime_paths
    ]
    regression_runtimes = [
        (path, load_typed_report(path, "production_runtime_evaluation"))
        for path in regression_runtime_paths
    ]
    if validation.get("passed") is not True:
        raise ValueError("dataset validation report must pass before evidence can be indexed")
    if training.get("passed") is not True:
        raise ValueError("training run report must pass before evidence can be indexed")
    if held_out.get("threshold_failures") != []:
        raise ValueError("held-out behavior matrix must pass before evidence can be indexed")

    training_dataset_id = required_string(validation, "dataset_id")
    training_dataset_version = required_string(validation, "dataset_version")
    training_dataset_checksum = required_string(validation, "dataset_checksum")
    if required_string(training, "dataset_id") != training_dataset_id:
        raise ValueError("training run dataset_id does not match dataset validation")
    if required_string(training, "dataset_version") != training_dataset_version:
        raise ValueError("training run dataset_version does not match dataset validation")
    if required_string(training, "dataset_checksum") != training_dataset_checksum:
        raise ValueError("training run dataset_checksum does not match dataset validation")
    adapter_id = required_string(training, "adapter_id")

    evaluation_dataset_id = required_string(held_out, "dataset_id")
    evaluation_dataset_version = required_string(held_out, "dataset_version")
    held_out_modes = require_mode_records(held_out.get("modes"), "held-out behavior matrix")
    held_out_adapter_ids = {
        required_string(record, "adapter_id")
        for mode, record in held_out_modes.items()
        if mode in {"adapter", "adapter_rag"}
    }
    if held_out_adapter_ids != {adapter_id}:
        raise ValueError("held-out behavior matrix adapter identity does not match training run")
    regression_summary = held_out.get("regression")
    if not isinstance(regression_summary, dict):
        raise ValueError("held-out behavior matrix must reference a regression evaluation")
    regression_dataset_id = required_string(regression_summary, "dataset_id")
    regression_dataset_version = required_string(regression_summary, "dataset_version")
    if (regression_dataset_id, regression_dataset_version) == (
        evaluation_dataset_id,
        evaluation_dataset_version,
    ):
        raise ValueError("behavior and regression evidence must use separate datasets")

    runtime_modes: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    for path, runtime in runtimes:
        mode = required_string(runtime, "evaluation_mode")
        if mode in runtime_modes:
            raise ValueError(f"duplicate production runtime mode {mode}")
        runtime_modes[mode] = (path, runtime)
        identity = (
            required_string(runtime, "dataset_id"),
            required_string(runtime, "dataset_version"),
        )
        if identity != (evaluation_dataset_id, evaluation_dataset_version):
            raise ValueError(f"{mode} production runtime dataset does not match held-out matrix")
        runtime_adapter_id = runtime.get("adapter_id")
        if mode in {"adapter", "adapter_rag"} and runtime_adapter_id != adapter_id:
            raise ValueError(f"{mode} production runtime adapter identity does not match training run")
        if mode in {"base", "base_rag"} and runtime_adapter_id is not None:
            raise ValueError(f"{mode} production runtime must not identify an adapter")
    if set(runtime_modes) != RUNTIME_MODES:
        missing = sorted(RUNTIME_MODES - set(runtime_modes))
        extra = sorted(set(runtime_modes) - RUNTIME_MODES)
        raise ValueError(f"production runtime reports require four modes; missing={missing}, extra={extra}")

    regression_modes: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    for path, runtime in regression_runtimes:
        mode = required_string(runtime, "evaluation_mode")
        if mode in regression_modes:
            raise ValueError(f"duplicate regression runtime mode {mode}")
        regression_modes[mode] = (path, runtime)
        identity = (
            required_string(runtime, "dataset_id"),
            required_string(runtime, "dataset_version"),
        )
        if identity != (regression_dataset_id, regression_dataset_version):
            raise ValueError(f"{mode} regression runtime dataset does not match held-out matrix")
        runtime_adapter_id = runtime.get("adapter_id")
        if mode == "adapter_rag" and runtime_adapter_id != adapter_id:
            raise ValueError("adapter_rag regression adapter identity does not match training run")
        if mode == "base_rag" and runtime_adapter_id is not None:
            raise ValueError("base_rag regression must not identify an adapter")
    if set(regression_modes) != {"base_rag", "adapter_rag"}:
        raise ValueError("regression runtime reports require base_rag and adapter_rag modes")

    artifacts = [
        artifact(dataset_validation_path, "dataset_validation"),
        artifact(training_run_path, "training_run"),
        artifact(held_out_behavior_path, "held_out_behavior_matrix"),
        *(
            artifact(
                path,
                "production_runtime_evaluation",
                evaluation_mode=mode,
                evaluation_scope="behavior",
            )
            for mode, (path, _) in sorted(runtime_modes.items())
        ),
        *(
            artifact(
                path,
                "production_runtime_evaluation",
                evaluation_mode=mode,
                evaluation_scope="regression",
            )
            for mode, (path, _) in sorted(regression_modes.items())
        ),
    ]
    return EvaluationEvidenceIndex(
        generated_at=datetime.now(UTC),
        training_dataset_id=training_dataset_id,
        training_dataset_version=training_dataset_version,
        training_dataset_checksum=training_dataset_checksum,
        evaluation_dataset_id=evaluation_dataset_id,
        evaluation_dataset_version=evaluation_dataset_version,
        regression_dataset_id=regression_dataset_id,
        regression_dataset_version=regression_dataset_version,
        adapter_id=adapter_id,
        artifacts=artifacts,
    )


def load_typed_report(path: Path, expected_type: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Report {path} must contain a JSON object")
    if value.get("report_type") != expected_type:
        raise ValueError(f"Report {path} must declare report_type={expected_type}")
    return value


def required_string(report: Mapping[str, Any], field: str) -> str:
    value = report.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Report field {field} must be a non-empty string")
    return value


def require_mode_records(value: object, label: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} modes must be an array")
    records: dict[str, Mapping[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{label} mode entries must be objects")
        mode = required_string(item, "mode")
        if mode in records:
            raise ValueError(f"{label} contains duplicate mode {mode}")
        records[mode] = item
    if set(records) != RUNTIME_MODES:
        raise ValueError(f"{label} must contain exactly the four evaluation modes")
    return records


def artifact(
    path: Path,
    report_type: Literal[
        "dataset_validation",
        "training_run",
        "held_out_behavior_matrix",
        "production_runtime_evaluation",
    ],
    *,
    evaluation_mode: str | None = None,
    evaluation_scope: Literal["behavior", "regression"] | None = None,
) -> EvidenceArtifact:
    return EvidenceArtifact(
        report_type=report_type,
        path=str(path),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        evaluation_mode=evaluation_mode,
        evaluation_scope=evaluation_scope,
    )


def write_evaluation_evidence_index(report: EvaluationEvidenceIndex, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
