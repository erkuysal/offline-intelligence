from __future__ import annotations

import copy
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
                "source_text_included": False,
                "generator": "phase-5-test-fixture-v1",
            }
        ],
        "support_review": {
            "status": "verified",
            "reviewer": "test-support-reviewer",
            "reviewed_at": "2026-07-15T12:00:00Z",
            "source_ids": ["public-backup"],
        },
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


def count_fixture_tokens(messages: object) -> int:
    assert isinstance(messages, (list, tuple))
    return 32


def test_load_training_dataset_accepts_pinned_reviewed_example(tmp_path: Path) -> None:
    manifest_path = write_dataset(tmp_path, [valid_example()])

    dataset = load_training_dataset(manifest_path, config_path=CONFIG_PATH)
    report = build_validation_report(
        manifest_path,
        config_path=CONFIG_PATH,
        token_counter=count_fixture_tokens,
    )

    assert dataset.manifest.dataset_id == "phase5-contract-test"
    assert dataset.manifest.split_percentages == (80, 10, 10)
    assert dataset.examples[0].example_id == "en-backup-behavior-001"
    assert report["passed"] is True
    assert report["report_type"] == "dataset_validation"
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

    report = build_validation_report(
        manifest_path,
        config_path=CONFIG_PATH,
        token_counter=count_fixture_tokens,
    )

    assert report["passed"] is False
    assert {issue["code"] for issue in report["issues"]} >= {
        "sensitive_content",
        "redistribution_prohibited",
    }


def test_support_review_and_restricted_source_text_are_enforced(tmp_path: Path) -> None:
    example = valid_example()
    del example["support_review"]
    example["provenance"][0]["redistribution"] = "restricted"
    example["provenance"][0]["source_text_included"] = True
    manifest_path = write_dataset(tmp_path, [example])

    with pytest.raises(TrainingDataError) as captured:
        load_training_dataset(manifest_path, config_path=CONFIG_PATH)

    assert issue_codes(captured.value) >= {
        "support_review_required",
        "restricted_source_text",
    }


def test_support_review_must_cover_cited_sources(tmp_path: Path) -> None:
    example = valid_example()
    example["support_review"]["source_ids"] = ["unknown-source"]
    manifest_path = write_dataset(tmp_path, [example])

    with pytest.raises(TrainingDataError) as captured:
        load_training_dataset(manifest_path, config_path=CONFIG_PATH)

    assert issue_codes(captured.value) >= {"support_review_sources", "unverified_target"}


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


def test_exact_duplicate_content_is_rejected_even_with_different_ids(tmp_path: Path) -> None:
    first = valid_example()
    second = copy.deepcopy(first)
    second["example_id"] = "en-backup-behavior-002"
    second["group_key"] = "independent-group-v1"
    second["template_family"] = "independent-template-v1"
    manifest_path = write_dataset(tmp_path, [first, second])

    with pytest.raises(TrainingDataError) as captured:
        load_training_dataset(manifest_path, config_path=CONFIG_PATH)

    assert "exact_duplicate" in issue_codes(captured.value)


def test_reserved_evaluation_source_is_rejected(tmp_path: Path) -> None:
    example = valid_example()
    example["provenance"][0]["source_uri"] = (
        "file://evaluation/datasets/dense-baseline-v1.jsonl"
    )
    manifest_path = write_dataset(tmp_path, [example])

    with pytest.raises(TrainingDataError) as captured:
        load_training_dataset(manifest_path, config_path=CONFIG_PATH)

    assert "reserved_evaluation_leakage" in issue_codes(captured.value)


def test_phase_5_evaluation_source_is_always_protected(tmp_path: Path) -> None:
    example = valid_example()
    example["provenance"][0]["source_uri"] = (
        "file://evaluation/datasets/phase-5-behavior-v1.jsonl"
    )
    manifest_path = write_dataset(tmp_path, [example])

    with pytest.raises(TrainingDataError) as captured:
        load_training_dataset(manifest_path, config_path=CONFIG_PATH)

    assert "reserved_evaluation_leakage" in issue_codes(captured.value)


def test_grouped_splits_and_checksums_are_deterministic(tmp_path: Path) -> None:
    english = valid_example()
    turkish = copy.deepcopy(english)
    turkish["example_id"] = "tr-backup-behavior-001"
    turkish["language"] = "tr"
    turkish["group_key"] = "yedekleme-davranisi-v1"
    turkish["messages"] = [
        {"role": "user", "content": "Örnek yedekleme ne zaman çalışır?"},
        {
            "role": "assistant",
            "content": "Örnek yedekleme her gece çalışır. [public-backup#schedule]",
        },
    ]
    manifest_path = write_dataset(tmp_path, [english, turkish])

    first = build_validation_report(
        manifest_path,
        config_path=CONFIG_PATH,
        token_counter=count_fixture_tokens,
    )
    second = build_validation_report(
        manifest_path,
        config_path=CONFIG_PATH,
        token_counter=count_fixture_tokens,
    )

    assert first["passed"] is True
    assert first["split_checksum"] == second["split_checksum"]
    assert first["dataset_checksum"] == second["dataset_checksum"]
    assert first["split_assignments"] == second["split_assignments"]
    assert len(set(first["split_assignments"].values())) == 1
    assert first["language_counts"] == {"en": 1, "tr": 1}


def test_near_duplicates_are_reported_and_kept_in_one_split(tmp_path: Path) -> None:
    first = valid_example()
    shared_question = " ".join(f"word{index}" for index in range(40))
    first["messages"][0]["content"] = shared_question
    second = copy.deepcopy(first)
    second["example_id"] = "en-near-duplicate-002"
    second["group_key"] = "near-duplicate-independent-v2"
    second["template_family"] = "near-duplicate-independent-v2"
    second["messages"][0]["content"] = shared_question.replace("word20", "changed20")
    manifest_path = write_dataset(tmp_path, [first, second])

    report = build_validation_report(
        manifest_path,
        config_path=CONFIG_PATH,
        token_counter=count_fixture_tokens,
    )

    assert report["passed"] is True
    assert report["duplicates"]["near_pair_count"] == 1
    assert len(set(report["split_assignments"].values())) == 1


def test_rendered_sequence_limit_and_explicit_split_conflicts_fail(tmp_path: Path) -> None:
    first = valid_example()
    first["intended_split"] = "train"
    second = copy.deepcopy(first)
    second["example_id"] = "tr-backup-behavior-002"
    second["language"] = "tr"
    second["intended_split"] = "held_out"
    second["messages"] = [
        {"role": "user", "content": "Yedekleme zamanını belirt."},
        {
            "role": "assistant",
            "content": "Yedekleme geceleri çalışır. [public-backup#schedule]",
        },
    ]
    manifest_path = write_dataset(tmp_path, [first, second])

    report = build_validation_report(
        manifest_path,
        config_path=CONFIG_PATH,
        token_counter=lambda messages: 1025,
    )

    assert report["passed"] is False
    assert set(report["rejection_reason_counts"]) >= {"sequence_too_long", "split_conflict"}


def test_training_data_cli_returns_zero_for_valid_and_one_for_invalid(tmp_path: Path) -> None:
    manifest_path = write_dataset(tmp_path, [valid_example()])
    output_path = tmp_path / "report.json"
    args = Namespace(
        manifest=str(manifest_path),
        config=str(CONFIG_PATH),
        output=str(output_path),
        token_counter=count_fixture_tokens,
    )

    assert manage.training_data_validate(args) == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["passed"] is True

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["examples_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert manage.training_data_validate(args) == 1
    assert json.loads(output_path.read_text(encoding="utf-8"))["passed"] is False
