from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from training.foundation import (
    TrainingFoundationError,
    collect_preflight_report,
    get_hugging_face_token,
    load_training_config,
    parse_compute_capability,
    write_json_report,
)


ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "training" / "gemma3-1b-lora-v1.json"


def test_training_config_pins_model_environment_and_calibration_lengths() -> None:
    config = load_training_config(CONFIG_PATH)

    assert config["base_model"]["repo_id"] == "google/gemma-3-1b-it"
    assert config["base_model"]["revision"] == "dcc83ea841ab6100d6b47a070329e1ba4cf78752"
    assert config["environment"]["python"] == "3.12.11"
    assert config["training"]["sequence_lengths"] == [1024, 2048]
    assert config["training"]["approved_max_sequence_length"] == 1024
    assert config["training"]["attention_implementation"] == "eager"
    assert config["training"]["deterministic_algorithms"] is True
    assert config["training"]["lora"]["rank"] == 8
    assert config["training"]["optimizer"] == {
        "name": "adamw_torch",
        "learning_rate": 0.0001,
        "betas": [0.9, 0.999],
        "epsilon": 1e-8,
        "weight_decay": 0.01,
        "amsgrad": False,
        "maximize": False,
        "foreach": False,
        "capturable": False,
        "differentiable": False,
        "fused": False,
    }
    assert config["training"]["scheduler"] == {"name": "cosine", "warmup_ratio": 0.03}
    assert config["training"]["search"]["ranks"] == [8, 16]
    assert len(config["training"]["search"]["learning_rates"]) <= 2
    template_path = ROOT / config["prompt_contract"]["chat_template_path"]
    assert hashlib.sha256(template_path.read_bytes()).hexdigest() == (
        config["prompt_contract"]["chat_template_sha256"]
    )
    assert config["prompt_contract"]["tokenizer_vocab_size"] == 262144
    assert config["base_model"]["accepted_runtime_file_sha256"] == (
        "8ccc5cd1f1b3602548715ae25a66ed73fd5dc68a210412eea643eb20eb75a135"
    )


def test_training_config_rejects_unpinned_package(tmp_path: Path) -> None:
    config = load_training_config(CONFIG_PATH)
    config["environment"]["packages"]["torch"] = ">=2"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(TrainingFoundationError, match="exact versions"):
        load_training_config(path)


def test_preflight_passes_with_matching_injected_environment(tmp_path: Path) -> None:
    config = load_training_config(CONFIG_PATH)
    expected_packages = config["environment"]["packages"]

    report = collect_preflight_report(
        config,
        cache_dir=tmp_path,
        environment={"HF_TOKEN": "test-only-token"},
        python_version=lambda: config["environment"]["python"],
        installed_version=lambda package: expected_packages.get(package),
        nvidia_smi=lambda: {
            "name": "NVIDIA GeForce RTX 5070",
            "memory_total_mib": 12227,
            "driver_version": "610.62",
            "compute_capability": "12.0",
        },
        torch_cuda=lambda: {
            "torch_cuda_version": "13.0",
            "bf16_supported": True,
            "device_name": "NVIDIA GeForce RTX 5070",
            "device_capability": "12.0",
        },
    )

    failed_checks = [check["name"] for check in report["checks"] if not check["passed"]]
    assert failed_checks == []
    assert report["passed"] is True
    assert report["platform"]["gpu"]["memory_total_mib"] == 12227
    assert report["base_model"]["revision"] == config["base_model"]["revision"]


def test_preflight_reports_missing_token_packages_cuda_and_small_gpu(tmp_path: Path) -> None:
    config = load_training_config(CONFIG_PATH)

    report = collect_preflight_report(
        config,
        cache_dir=tmp_path,
        environment={},
        python_version=lambda: "3.14.6",
        installed_version=lambda _package: None,
        nvidia_smi=lambda: {
            "name": "NVIDIA Test GPU",
            "memory_total_mib": 4096,
            "driver_version": "1.0",
            "compute_capability": "8.0",
        },
        torch_cuda=lambda: None,
    )

    failed_checks = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "package:torch" in failed_checks
    assert "gpu_name" in failed_checks
    assert "gpu_vram" in failed_checks
    assert "gpu_compute_capability" in failed_checks
    assert "torch_cuda" in failed_checks
    assert "bf16" in failed_checks
    assert "model_access_token" in failed_checks
    assert report["passed"] is False


def test_preflight_report_does_not_persist_token(tmp_path: Path) -> None:
    config = load_training_config(CONFIG_PATH)
    report = collect_preflight_report(
        config,
        cache_dir=tmp_path,
        environment={"HF_TOKEN": "must-not-be-written"},
        python_version=lambda: config["environment"]["python"],
        installed_version=lambda package: config["environment"]["packages"].get(package),
        nvidia_smi=lambda: None,
        torch_cuda=lambda: None,
    )
    output = tmp_path / "report.json"

    write_json_report(report, output)

    assert "must-not-be-written" not in output.read_text(encoding="utf-8")


def test_hugging_face_token_prefers_explicit_environment() -> None:
    assert get_hugging_face_token({"HF_TOKEN": "process-token"}) == "process-token"
    assert get_hugging_face_token({}) is None


def test_compute_capability_comparison_is_numeric() -> None:
    assert parse_compute_capability("12.0") > parse_compute_capability("9.0")
    with pytest.raises(TrainingFoundationError, match="Invalid compute capability"):
        parse_compute_capability("blackwell")
