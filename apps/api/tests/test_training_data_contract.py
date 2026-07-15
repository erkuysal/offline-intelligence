from __future__ import annotations

import hashlib
import json
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

import manage
from training.data_contract import (
    TrainingDataError,
    build_validation_report,
    load_training_dataset,
)


ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "training" / "gemma3-1b-lora-v1.json"


def valid_example() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "example_id": "en-backup-behavior-001",
        "task": "grounded_answer",
        "language": "en",
        "messages": [
            {"role": "user", "content": "When does the example backup run?"},
            {
                "role": "assistant",
                "content": "The example backup runs nightly. [public-backup#schedule]",
            },
        ],
        "expected_citations": [
            {"source_id": "public-backup", "passage_id": "schedule"}
        ],
        "provenance": [
            {
                "source_id": "public-backup",
                "source_uri": "synthetic://phase-5/public-backup",
                "license": "CC0-1.0",
                "redistribution": "allowed",
                "synthetic": True,
                "generator": "phase-5-test-fixture-v1",
            }
        ],
        "sensitivity": "public",
        "approval": {
            "status": "approved",
            "reviewer": "test-reviewer",
            "reviewed_at": "2026-07-15T12:00:00Z",
            "scope": "training-and-redistribution",
        },
        "template_family": "backup-behavior-v1",
        "group_key": "backup-behavior-v1",
        "intended_split": "auto",
    }


def write_dataset(tmp_path: Path, examples: list[dict[str, Any]]) -> Path:
    examples_path = tmp_path / "examples.jsonl"
    encoded = "".join(
        json.dumps(example, ensure_ascii=False, separators=(",", ":")) + "\n"
        for example in examples
    ).encode()
    examples_path.write_bytes(encoded)
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    manifest = {
        "schema_version": "1.0",
        "dataset_id": "phase5-contract-test",
        "dataset_version": "1.0.0",
        "description": "Synthetic contract fixture; not production training data",
        "examples_file": "examples.jsonl",
        "examples_sha256": hashlib.sha256(encoded).hexdigest(),
        "example_schema": "../schemas/training-example-v1.schema.json",
        "template_contract": {
            "base_model_revision": config["base_model"]["revision"],
            "chat_template_sha256": config["prompt_contract"]["chat_template_sha256"],
            "max_sequence_length": config["training"]["approved_max_sequence_length"],
        },
        "split_policy": {
            "seed": 20260715,
            "train_percent": 80,
            "validation_percent": 10,
            "held_out_percent": 10,
            "group_field": "group_key",
        },
        "reserved_evaluation_datasets": ["evaluation/datasets/dense-baseline-v1.jsonl"],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def issue_codes(error: TrainingDataError) -> set[str]:
    return {issue.code for issue in error.issues}


def test_load_training_dataset_accepts_pinned_reviewed_example(tmp_path: Path) -> None:
    manifest_path = write_dataset(tmp_path, [valid_example()])

    dataset = load_training_dataset(manifest_path, config_path=CONFIG_PATH)
    report = build_validation_report(manifest_path, config_path=CONFIG_PATH)

    assert dataset.manifest.dataset_id == "phase5-contract-test"
    assert dataset.manifest.split_percentages == (80, 10, 10)
    assert dataset.examples[0].example_id == "en-backup-behavior-001"
    assert report["passed"] is True
    assert report["task_counts"] == {"grounded_answer": 1}
    assert report["language_counts"] == {"en": 1}


def test_synthetic_or_internal_examples_require_explicit_approval(tmp_path: Path) -> None:
    example = valid_example()
    del example["approval"]
    example["sensitivity"] = "internal-approved"
    manifest_path = write_dataset(tmp_path, [example])

    with pytest.raises(TrainingDataError) as captured:
        load_training_dataset(manifest_path, config_path=CONFIG_PATH)

    assert "approval_required" in issue_codes(captured.value)


def test_sensitive_content_and_prohibited_sources_fail_validation(tmp_path: Path) -> None:
    example = valid_example()
    example["messages"][0]["content"] = "Use token hf_abcdefghijklmnopqrstuvwxyz123456."
    example["provenance"][0]["redistribution"] = "prohibited"
    manifest_path = write_dataset(tmp_path, [example])

    report = build_validation_report(manifest_path, config_path=CONFIG_PATH)

    assert report["passed"] is False
    assert {issue["code"] for issue in report["issues"]} >= {
        "sensitive_content",
        "redistribution_prohibited",
    }


def test_roles_citations_and_json_targets_are_semantically_validated(tmp_path: Path) -> None:
    example = valid_example()
    example["task"] = "json_output"
    example["expected_citations"] = []
    example["messages"] = [
        {"role": "user", "content": "Return the status object."},
        {"role": "user", "content": "Use the required schema."},
        {"role": "assistant", "content": '{"status":"unexpected"}'},
    ]
    example["target_json_schema"] = {
        "type": "object",
        "required": ["status"],
        "additionalProperties": False,
        "properties": {"status": {"type": "string", "enum": ["ok"]}},
    }
    manifest_path = write_dataset(tmp_path, [example])

    with pytest.raises(TrainingDataError) as captured:
        load_training_dataset(manifest_path, config_path=CONFIG_PATH)

    assert issue_codes(captured.value) >= {"role_order", "json_target_schema"}


def test_manifest_checksum_and_split_total_are_enforced(tmp_path: Path) -> None:
    manifest_path = write_dataset(tmp_path, [valid_example()])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["examples_sha256"] = "0" * 64
    manifest["split_policy"]["train_percent"] = 79
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(TrainingDataError) as captured:
        load_training_dataset(manifest_path, config_path=CONFIG_PATH)

    assert issue_codes(captured.value) >= {"examples_sha256_mismatch", "split_percentages"}


def test_training_data_cli_returns_zero_for_valid_and_one_for_invalid(tmp_path: Path) -> None:
    manifest_path = write_dataset(tmp_path, [valid_example()])
    output_path = tmp_path / "report.json"
    args = Namespace(
        manifest=str(manifest_path),
        config=str(CONFIG_PATH),
        output=str(output_path),
    )

    assert manage.training_data_validate(args) == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["passed"] is True

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["examples_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert manage.training_data_validate(args) == 1
    assert json.loads(output_path.read_text(encoding="utf-8"))["passed"] is False
