from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from training.data_contract import (
    DatasetAnalysis,
    TrainingDataset,
    TrainingExample,
    TrainingManifest,
)
from training.foundation import load_training_config
from training.trainer import (
    IGNORE_INDEX,
    TrainingRunError,
    build_run_manifest,
    encode_assistant_only,
    select_candidate_by_held_out_metrics,
    validate_adapter_checkpoint,
    validate_resume_manifest,
    validate_step_numerics,
)


ROOT = Path(__file__).resolve().parents[3]
V2_CONFIG_PATH = ROOT / "config/training/gemma3-1b-lora-v2.json"


class FakeChatTokenizer:
    pad_token_id = 0

    def apply_chat_template(
        self,
        conversation: list[dict[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> list[int]:
        assert tokenize is True
        tokens = [1]
        for message in conversation:
            role = {"system": 2, "user": 3, "assistant": 4}[message["role"]]
            tokens.extend([10, role])
            tokens.extend(100 + ord(character) for character in message["content"])
            tokens.append(11)
        if add_generation_prompt:
            tokens.extend([10, 4])
        return tokens


def dataset_and_analysis() -> tuple[TrainingDataset, DatasetAnalysis]:
    dataset = TrainingDataset(
        manifest=TrainingManifest(
            dataset_id="phase5-training",
            dataset_version="1.0.0",
            examples_path=Path("examples.jsonl"),
            examples_sha256="a" * 64,
            split_seed=7,
            split_percentages=(80, 10, 10),
            max_sequence_length=1024,
            reserved_evaluation_datasets=("evaluation.jsonl",),
        ),
        examples=(
            TrainingExample(
                example_id="example-one",
                task="grounded_answer",
                language="en",
                messages=({"role": "user", "content": "Q"}, {"role": "assistant", "content": "A"}),
                expected_citations=(),
                provenance=(),
                support_review={},
                sensitivity="public",
                template_family="family-one",
                group_key="group-one",
                intended_split="train",
                target_json_schema=None,
                approval=None,
            ),
        ),
    )
    analysis = DatasetAnalysis(
        assignments={"example-one": "train"},
        split_checksum="b" * 64,
        dataset_checksum="c" * 64,
        exact_duplicate_rate=0,
        near_duplicates=(),
        sequence_lengths={"example-one": 9},
    )
    return dataset, analysis


def test_assistant_only_mask_excludes_prompts_headers_and_padding() -> None:
    encoded = encode_assistant_only(
        FakeChatTokenizer(),
        [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "A"},
            {"role": "user", "content": "R"},
            {"role": "assistant", "content": "B"},
        ],
        max_sequence_length=32,
    )

    trained_tokens = [
        token for token, label in zip(encoded.input_ids, encoded.labels, strict=True)
        if label != IGNORE_INDEX
    ]
    assert trained_tokens == [165, 11, 166, 11]
    assert all(
        label == IGNORE_INDEX
        for label, attention in zip(encoded.labels, encoded.attention_mask, strict=True)
        if attention == 0
    )


def test_assistant_mask_rejects_overlength_sequence() -> None:
    with pytest.raises(TrainingRunError, match="maximum is 4"):
        encode_assistant_only(
            FakeChatTokenizer(),
            [{"role": "user", "content": "Q"}, {"role": "assistant", "content": "A"}],
            max_sequence_length=4,
        )


def test_run_manifest_records_reproducibility_inputs_and_bounded_override() -> None:
    config = load_training_config(ROOT / "config/training/gemma3-1b-lora-v1.json")
    dataset, analysis = dataset_and_analysis()

    manifest = build_run_manifest(config, dataset, analysis, rank=16, learning_rate=0.0002)

    assert manifest["base_model"]["revision"] == config["base_model"]["revision"]
    assert manifest["dataset"]["dataset_checksum"] == "c" * 64
    assert manifest["lora"]["rank"] == 16
    assert manifest["lora"]["alpha"] == 16
    assert manifest["optimizer"]["learning_rate"] == 0.0002
    assert manifest["scheduler"] == {"name": "cosine", "warmup_ratio": 0.03}
    assert manifest["environment"]["packages"]["peft"] == "0.19.1"
    assert len(manifest["run_fingerprint"]) == 64

    with pytest.raises(TrainingRunError, match="outside the bounded search"):
        build_run_manifest(config, dataset, analysis, rank=32)


def test_v2_manifest_pins_constant_warmup_schedule_and_selected_v1_hyperparameters() -> None:
    config = load_training_config(V2_CONFIG_PATH)
    dataset, analysis = dataset_and_analysis()

    manifest = build_run_manifest(config, dataset, analysis)

    assert manifest["scheduler"] == {"name": "constant_with_warmup", "warmup_steps": 5}
    assert manifest["lora"]["rank"] == 16
    assert manifest["lora"]["alpha"] == 16
    assert manifest["optimizer"]["learning_rate"] == 0.0002
    assert manifest["max_gradient_norm"] == 1.0


def test_resume_requires_byte_equivalent_manifest_content(tmp_path: Path) -> None:
    config = load_training_config(ROOT / "config/training/gemma3-1b-lora-v1.json")
    dataset, analysis = dataset_and_analysis()
    manifest = build_run_manifest(config, dataset, analysis)
    path = tmp_path / "run-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert validate_resume_manifest(manifest, path) == manifest
    mismatched = dict(manifest)
    mismatched["seed"] = 99
    with pytest.raises(TrainingRunError, match="does not exactly match"):
        validate_resume_manifest(mismatched, path)


@pytest.mark.parametrize(("loss", "gradient"), [(float("nan"), 1), (1, float("inf")), (1, -1)])
def test_non_finite_or_invalid_training_values_stop(loss: float, gradient: float) -> None:
    with pytest.raises(TrainingRunError):
        validate_step_numerics(loss, gradient)


def test_adapter_checkpoint_rejects_base_weights(tmp_path: Path) -> None:
    (tmp_path / "adapter_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "adapter_model.safetensors").write_bytes(b"adapter")
    validate_adapter_checkpoint(tmp_path)
    (tmp_path / "model.safetensors").write_bytes(b"base")
    with pytest.raises(TrainingRunError, match="base-model"):
        validate_adapter_checkpoint(tmp_path)


def test_candidate_selection_uses_held_out_failures_then_score() -> None:
    candidates: list[dict[str, Any]] = [
        {
            "adapter_id": "a",
            "training_loss": 0.1,
            "held_out": {"threshold_failures": 1, "behavior_score": 0.99},
        },
        {
            "adapter_id": "b",
            "training_loss": 0.5,
            "held_out": {"threshold_failures": 0, "behavior_score": 0.8},
        },
        {
            "adapter_id": "c",
            "training_loss": 0.2,
            "held_out": {"threshold_failures": 0, "behavior_score": 0.9},
        },
    ]
    assert select_candidate_by_held_out_metrics(candidates)["adapter_id"] == "c"
    with pytest.raises(TrainingRunError, match="training loss alone"):
        select_candidate_by_held_out_metrics([{"adapter_id": "x", "training_loss": 0.1}])
