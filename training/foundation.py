from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CONFIG_PATH = Path("config/training/gemma3-1b-lora-v1.json")


class TrainingFoundationError(ValueError):
    """Raised when the Phase 5 foundation configuration is invalid."""


def load_training_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingFoundationError(f"Could not load training configuration {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise TrainingFoundationError("Training configuration must be a JSON object")
    if payload.get("schema_version") != 1:
        raise TrainingFoundationError("Training configuration schema_version must be 1")

    required_sections = ("experiment_id", "base_model", "environment", "hardware", "training")
    missing = [section for section in required_sections if not payload.get(section)]
    if missing:
        raise TrainingFoundationError(
            f"Training configuration is missing required sections: {', '.join(missing)}"
        )

    base_model = payload["base_model"]
    if not isinstance(base_model, dict) or not base_model.get("repo_id"):
        raise TrainingFoundationError("base_model.repo_id is required")
    revision = base_model.get("revision")
    if not isinstance(revision, str) or len(revision) != 40:
        raise TrainingFoundationError("base_model.revision must be a pinned 40-character commit")

    environment = payload["environment"]
    if not isinstance(environment, dict) or not isinstance(environment.get("packages"), dict):
        raise TrainingFoundationError("environment.packages must contain pinned package versions")
    unpinned = [
        name
        for name, version in environment["packages"].items()
        if not isinstance(version, str) or not version or any(token in version for token in "*<>=~")
    ]
    if unpinned:
        raise TrainingFoundationError(f"Packages must use exact versions: {', '.join(unpinned)}")

    sequence_lengths = payload["training"].get("sequence_lengths")
    if sequence_lengths != [1024, 2048]:
        raise TrainingFoundationError("Initial calibration must cover 1024 and 2048 tokens")
    if payload["training"].get("approved_max_sequence_length") != 1024:
        raise TrainingFoundationError("Initial approved training length must be 1024 tokens")
    training = payload["training"]
    required_training_fields = {
        "precision",
        "fallback_precision",
        "micro_batch_size",
        "gradient_accumulation_steps",
        "gradient_checkpointing",
        "attention_implementation",
        "deterministic_algorithms",
        "seed",
        "epochs",
        "max_steps",
        "max_gradient_norm",
        "evaluation_steps",
        "checkpoint_steps",
        "optimizer",
        "scheduler",
        "lora",
        "search",
    }
    missing_training_fields = sorted(required_training_fields - training.keys())
    if missing_training_fields:
        raise TrainingFoundationError(
            "Training configuration is missing explicit fields: "
            + ", ".join(missing_training_fields)
        )
    optimizer = training["optimizer"]
    if set(optimizer) != {
        "name",
        "learning_rate",
        "betas",
        "epsilon",
        "weight_decay",
        "amsgrad",
        "maximize",
        "foreach",
        "capturable",
        "differentiable",
        "fused",
    }:
        raise TrainingFoundationError("optimizer must declare every supported setting exactly")
    if optimizer["name"] != "adamw_torch" or optimizer["learning_rate"] <= 0:
        raise TrainingFoundationError("only adamw_torch with a positive learning rate is supported")
    if optimizer["betas"] != [0.9, 0.999] or optimizer["epsilon"] <= 0:
        raise TrainingFoundationError("optimizer betas and epsilon must be explicit and valid")
    scheduler = training["scheduler"]
    ratio_scheduler = set(scheduler) == {"name", "warmup_ratio"}
    step_scheduler = set(scheduler) == {"name", "warmup_steps"}
    if not ratio_scheduler and not step_scheduler:
        raise TrainingFoundationError(
            "scheduler must declare exactly one explicit warmup_ratio or warmup_steps contract"
        )
    if scheduler["name"] not in {"linear", "cosine", "constant_with_warmup"}:
        raise TrainingFoundationError("scheduler name is unsupported")
    if ratio_scheduler and not 0 <= scheduler["warmup_ratio"] < 1:
        raise TrainingFoundationError("scheduler warmup_ratio is invalid")
    if step_scheduler and (
        not isinstance(scheduler["warmup_steps"], int)
        or isinstance(scheduler["warmup_steps"], bool)
        or scheduler["warmup_steps"] <= 0
    ):
        raise TrainingFoundationError("scheduler warmup_steps must be a positive integer")
    if scheduler["name"] == "constant_with_warmup" and not step_scheduler:
        raise TrainingFoundationError(
            "constant_with_warmup requires an explicit positive warmup_steps value"
        )
    search = training["search"]
    ranks = search.get("ranks")
    if (
        not isinstance(ranks, list)
        or not ranks
        or len(ranks) != len(set(ranks))
        or not set(ranks) <= {8, 16}
    ):
        raise TrainingFoundationError(
            "LoRA search ranks must be a non-empty unique subset of the approved ranks 8 and 16"
        )
    learning_rates = search.get("learning_rates")
    if (
        not isinstance(learning_rates, list)
        or not 1 <= len(learning_rates) <= 2
        or len(learning_rates) != len(set(learning_rates))
        or not all(
            isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0
            for rate in learning_rates
        )
    ):
        raise TrainingFoundationError("search must define one or two unique positive learning rates")
    candidate_count = len(ranks) * len(learning_rates)
    if search.get("maximum_candidates") != candidate_count or candidate_count > 4:
        raise TrainingFoundationError("maximum_candidates must match the bounded search grid")
    if search.get("selection_source") != "held_out_behavior_metrics":
        raise TrainingFoundationError("candidate selection must use held-out behavior metrics")
    export = payload.get("export")
    if export is not None:
        if not isinstance(export, dict) or set(export) != {
            "schema_version",
            "llama_cpp_revision",
            "converter_path",
            "gguf_output_type",
            "runtime_adapter_scale",
        }:
            raise TrainingFoundationError("export must declare every compatibility setting exactly")
        if export["schema_version"] != 1:
            raise TrainingFoundationError("export schema_version must be 1")
        if not isinstance(export["llama_cpp_revision"], str) or len(
            export["llama_cpp_revision"]
        ) != 40:
            raise TrainingFoundationError("export llama_cpp_revision must be a pinned commit")
        if export["converter_path"] != "convert_lora_to_gguf.py":
            raise TrainingFoundationError("export converter_path is unsupported")
        if export["gguf_output_type"] not in {"f16", "bf16"}:
            raise TrainingFoundationError("export GGUF output type must preserve 16-bit precision")
        if export["runtime_adapter_scale"] != 1.0:
            raise TrainingFoundationError("initial runtime adapter scale must be exactly 1.0")
    positive_integer_fields = (
        "micro_batch_size",
        "gradient_accumulation_steps",
        "epochs",
        "max_steps",
        "evaluation_steps",
        "checkpoint_steps",
    )
    if any(
        not isinstance(training[field], int)
        or isinstance(training[field], bool)
        or training[field] <= 0
        for field in positive_integer_fields
    ):
        raise TrainingFoundationError("batch, epoch, step, and cadence values must be positive integers")
    if training["micro_batch_size"] != 1:
        raise TrainingFoundationError("the calibrated micro_batch_size is exactly 1")
    if training["attention_implementation"] != "eager":
        raise TrainingFoundationError("training attention_implementation must be deterministic eager")
    if training["deterministic_algorithms"] is not True:
        raise TrainingFoundationError("deterministic_algorithms must be enabled")
    if not isinstance(training["seed"], int) or isinstance(training["seed"], bool):
        raise TrainingFoundationError("training seed must be an integer")
    if not isinstance(training["max_gradient_norm"], (int, float)) or training[
        "max_gradient_norm"
    ] <= 0:
        raise TrainingFoundationError("max_gradient_norm must be positive")
    lora = training["lora"]
    if set(lora) != {
        "rank",
        "alpha",
        "dropout",
        "bias",
        "fan_in_fan_out",
        "init_lora_weights",
        "use_rslora",
        "use_dora",
        "target_modules",
    }:
        raise TrainingFoundationError("LoRA must declare every supported setting exactly")
    if lora["rank"] not in search["ranks"] or lora["alpha"] <= 0:
        raise TrainingFoundationError("LoRA rank or alpha is invalid")
    if not 0 <= lora["dropout"] < 1 or lora["bias"] != "none":
        raise TrainingFoundationError("LoRA dropout or bias is invalid")
    if not isinstance(lora["target_modules"], list) or not lora["target_modules"]:
        raise TrainingFoundationError("LoRA target_modules must be a non-empty list")
    return payload


def parse_compute_capability(value: str) -> tuple[int, int]:
    try:
        major, minor = value.split(".", 1)
        return int(major), int(minor)
    except (AttributeError, TypeError, ValueError) as exc:
        raise TrainingFoundationError(f"Invalid compute capability: {value!r}") from exc


def read_nvidia_smi() -> dict[str, Any] | None:
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version,compute_cap",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    name, memory_mib, driver, compute_capability = [
        part.strip() for part in result.stdout.splitlines()[0].split(",", 3)
    ]
    return {
        "name": name,
        "memory_total_mib": int(memory_mib),
        "driver_version": driver,
        "compute_capability": compute_capability,
    }


def read_torch_cuda() -> dict[str, Any] | None:
    try:
        import torch  # type: ignore[import-not-found]
    except (ImportError, OSError):
        return None
    if not torch.cuda.is_available():
        return None
    return {
        "torch_cuda_version": torch.version.cuda,
        "bf16_supported": bool(torch.cuda.is_bf16_supported()),
        "device_name": torch.cuda.get_device_name(0),
        "device_capability": ".".join(str(part) for part in torch.cuda.get_device_capability(0)),
    }


def _installed_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def get_hugging_face_token(environment: Mapping[str, str] | None = None) -> str | None:
    current_environment = environment if environment is not None else os.environ
    if token := current_environment.get("HF_TOKEN"):
        return token
    if environment is not None:
        return None
    try:
        from huggingface_hub import get_token  # type: ignore[import-not-found]
    except (ImportError, OSError):
        return None
    return get_token()


def has_hugging_face_token(environment: Mapping[str, str] | None = None) -> bool:
    return bool(get_hugging_face_token(environment))


def collect_preflight_report(
    config: Mapping[str, Any],
    *,
    cache_dir: Path,
    environment: Mapping[str, str] | None = None,
    python_version: Callable[[], str] = platform.python_version,
    installed_version: Callable[[str], str | None] = _installed_version,
    nvidia_smi: Callable[[], dict[str, Any] | None] = read_nvidia_smi,
    torch_cuda: Callable[[], dict[str, Any] | None] = read_torch_cuda,
) -> dict[str, Any]:
    current_environment = environment if environment is not None else os.environ
    checks: list[dict[str, Any]] = []

    def add_check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    expected_python = str(config["environment"]["python"])
    actual_python = python_version()
    add_check(
        "python_version",
        actual_python == expected_python,
        f"expected {expected_python}; found {actual_python}",
    )

    package_versions: dict[str, str | None] = {}
    for package, expected in config["environment"]["packages"].items():
        actual = installed_version(package)
        package_versions[package] = actual
        add_check(
            f"package:{package}",
            actual == expected,
            f"expected {expected}; found {actual or 'not installed'}",
        )

    gpu = nvidia_smi()
    hardware = config["hardware"]
    if gpu is None:
        add_check("nvidia_smi", False, "no NVIDIA GPU was reported by nvidia-smi")
    else:
        expected_name = str(hardware["device_name_contains"])
        add_check("gpu_name", expected_name in gpu["name"], f"found {gpu['name']}")
        minimum_vram = int(hardware["minimum_vram_mib"])
        add_check(
            "gpu_vram",
            gpu["memory_total_mib"] >= minimum_vram,
            f"required >= {minimum_vram} MiB; found {gpu['memory_total_mib']} MiB",
        )
        required_capability = parse_compute_capability(hardware["minimum_compute_capability"])
        actual_capability = parse_compute_capability(gpu["compute_capability"])
        add_check(
            "gpu_compute_capability",
            actual_capability >= required_capability,
            f"required >= {hardware['minimum_compute_capability']}; found {gpu['compute_capability']}",
        )

    cuda = torch_cuda()
    add_check(
        "torch_cuda",
        cuda is not None,
        "PyTorch CUDA is available" if cuda is not None else "PyTorch cannot access CUDA",
    )
    if config["training"]["precision"] == "bf16":
        add_check(
            "bf16",
            bool(cuda and cuda["bf16_supported"]),
            "BF16 is supported" if cuda and cuda["bf16_supported"] else "BF16 is unavailable",
        )

    disk_target = cache_dir
    while not disk_target.exists() and disk_target != disk_target.parent:
        disk_target = disk_target.parent
    disk = shutil.disk_usage(disk_target)
    free_disk_gib = disk.free / (1024**3)
    minimum_disk_gib = float(hardware["minimum_free_disk_gib"])
    add_check(
        "free_disk",
        free_disk_gib >= minimum_disk_gib,
        f"required >= {minimum_disk_gib:g} GiB; found {free_disk_gib:.2f} GiB at {cache_dir}",
    )

    gated = bool(config["base_model"].get("gated"))
    token_configured = has_hugging_face_token(
        current_environment if environment is not None else None
    )
    add_check(
        "model_access_token",
        not gated or token_configured,
        "HF_TOKEN is configured"
        if token_configured
        else "HF_TOKEN is required for the gated base model and is not configured",
    )

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "experiment_id": config["experiment_id"],
        "base_model": {
            "repo_id": config["base_model"]["repo_id"],
            "revision": config["base_model"]["revision"],
            "gated": gated,
        },
        "platform": {
            "python": actual_python,
            "system": platform.platform(),
            "executable": sys.executable,
            "packages": package_versions,
            "gpu": gpu,
            "torch_cuda": cuda,
            "free_disk_gib": round(free_disk_gib, 3),
        },
        "checks": checks,
        "passed": all(check["passed"] for check in checks),
    }


def write_json_report(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def format_preflight_summary(report: Mapping[str, Any]) -> str:
    lines = [
        f"Training preflight: {'PASS' if report['passed'] else 'FAIL'}",
        f"Experiment: {report['experiment_id']}",
    ]
    for check in report["checks"]:
        marker = "PASS" if check["passed"] else "FAIL"
        lines.append(f"[{marker}] {check['name']}: {check['detail']}")
    return "\n".join(lines)
