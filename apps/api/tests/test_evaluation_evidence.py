import json
from pathlib import Path

import pytest

from training.evaluation_evidence import build_evaluation_evidence_index


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def evidence_paths(tmp_path: Path) -> tuple[Path, Path, Path, list[Path], list[Path]]:
    validation = write_json(
        tmp_path / "validation.json",
        {
            "report_type": "dataset_validation",
            "passed": True,
            "dataset_id": "training-v1",
            "dataset_version": "1.0.0",
            "dataset_checksum": "a" * 64,
        },
    )
    training = write_json(
        tmp_path / "training.json",
        {
            "report_type": "training_run",
            "passed": True,
            "dataset_id": "training-v1",
            "dataset_version": "1.0.0",
            "dataset_checksum": "a" * 64,
            "adapter_id": "adapter-v1",
        },
    )
    modes = [
        {"mode": "base", "adapter_id": None},
        {"mode": "base_rag", "adapter_id": None},
        {"mode": "adapter", "adapter_id": "adapter-v1"},
        {"mode": "adapter_rag", "adapter_id": "adapter-v1"},
    ]
    held_out = write_json(
        tmp_path / "held-out.json",
        {
            "report_type": "held_out_behavior_matrix",
            "dataset_id": "behavior-v1",
            "dataset_version": "1.0.0",
            "threshold_failures": [],
            "modes": modes,
            "regression": {
                "dataset_id": "phase-4-regression-v1",
                "dataset_version": "1.0.0",
            },
        },
    )
    runtime_paths = []
    for mode in modes:
        runtime_paths.append(
            write_json(
                tmp_path / f"runtime-{mode['mode']}.json",
                {
                    "report_type": "production_runtime_evaluation",
                    "evaluation_mode": mode["mode"],
                    "dataset_id": "behavior-v1",
                    "dataset_version": "1.0.0",
                    "adapter_id": mode["adapter_id"],
                },
            )
        )
    regression_paths = []
    for mode in ("base_rag", "adapter_rag"):
        regression_paths.append(
            write_json(
                tmp_path / f"regression-{mode}.json",
                {
                    "report_type": "production_runtime_evaluation",
                    "evaluation_mode": mode,
                    "dataset_id": "phase-4-regression-v1",
                    "dataset_version": "1.0.0",
                    "adapter_id": "adapter-v1" if mode == "adapter_rag" else None,
                },
            )
        )
    return validation, training, held_out, runtime_paths, regression_paths


def test_evidence_index_separates_and_cross_references_report_families(tmp_path: Path) -> None:
    validation, training, held_out, runtimes, regressions = evidence_paths(tmp_path)

    report = build_evaluation_evidence_index(
        dataset_validation_path=validation,
        training_run_path=training,
        held_out_behavior_path=held_out,
        runtime_paths=runtimes,
        regression_runtime_paths=regressions,
    )

    assert report.report_type == "phase_5_evidence_index"
    assert report.training_dataset_checksum == "a" * 64
    assert report.evaluation_dataset_id == "behavior-v1"
    assert report.adapter_id == "adapter-v1"
    assert report.promotion_passed is True
    assert report.regression_dataset_id == "phase-4-regression-v1"
    assert len(report.artifacts) == 9
    assert {artifact.evaluation_mode for artifact in report.artifacts if artifact.evaluation_mode} == {
        "base",
        "base_rag",
        "adapter",
        "adapter_rag",
    }
    assert all(len(artifact.sha256) == 64 for artifact in report.artifacts)
    assert sum(artifact.evaluation_scope == "regression" for artifact in report.artifacts) == 2


def test_evidence_index_records_rejected_promotion(tmp_path: Path) -> None:
    validation, training, held_out, runtimes, regressions = evidence_paths(tmp_path)
    payload = json.loads(held_out.read_text(encoding="utf-8"))
    payload["threshold_failures"] = ["adapter_rag: json_schema_validity failed"]
    write_json(held_out, payload)

    report = build_evaluation_evidence_index(
        dataset_validation_path=validation,
        training_run_path=training,
        held_out_behavior_path=held_out,
        runtime_paths=runtimes,
        regression_runtime_paths=regressions,
    )

    assert report.promotion_passed is False
    held_out_artifact = next(
        artifact for artifact in report.artifacts if artifact.report_type == "held_out_behavior_matrix"
    )
    assert held_out_artifact.sha256


def test_evidence_index_rejects_training_dataset_mismatch(tmp_path: Path) -> None:
    validation, training, held_out, runtimes, regressions = evidence_paths(tmp_path)
    payload = json.loads(training.read_text(encoding="utf-8"))
    payload["dataset_checksum"] = "b" * 64
    write_json(training, payload)

    with pytest.raises(ValueError, match="dataset_checksum does not match"):
        build_evaluation_evidence_index(
            dataset_validation_path=validation,
            training_run_path=training,
            held_out_behavior_path=held_out,
            runtime_paths=runtimes,
            regression_runtime_paths=regressions,
        )


def test_evidence_index_rejects_runtime_adapter_mismatch(tmp_path: Path) -> None:
    validation, training, held_out, runtimes, regressions = evidence_paths(tmp_path)
    adapter_runtime = next(path for path in runtimes if path.name == "runtime-adapter.json")
    payload = json.loads(adapter_runtime.read_text(encoding="utf-8"))
    payload["adapter_id"] = "wrong-adapter"
    write_json(adapter_runtime, payload)

    with pytest.raises(ValueError, match="adapter identity does not match"):
        build_evaluation_evidence_index(
            dataset_validation_path=validation,
            training_run_path=training,
            held_out_behavior_path=held_out,
            runtime_paths=runtimes,
            regression_runtime_paths=regressions,
        )
