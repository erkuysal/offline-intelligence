from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from training.foundation import write_json_report
from training.trainer import TrainingRunError, validate_adapter_checkpoint


TOKENIZER_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingRunError(f"could not read JSON artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TrainingRunError(f"JSON artifact must be an object: {path}")
    return payload


def validate_peft_export_compatibility(
    config: Mapping[str, Any], adapter_path: Path
) -> dict[str, Any]:
    try:
        from safetensors import safe_open  # type: ignore[import-not-found]
    except (ImportError, OSError) as exc:
        raise TrainingRunError("adapter export requires safetensors") from exc
    validate_adapter_checkpoint(adapter_path)
    adapter_config = _load_json(adapter_path / "adapter_config.json")
    training = config["training"]
    lora = training["lora"]
    checks = {
        "base_model": adapter_config.get("base_model_name_or_path")
        == config["base_model"]["repo_id"],
        "peft_type": adapter_config.get("peft_type") == "LORA",
        "task_type": adapter_config.get("task_type") == "CAUSAL_LM",
        "rank": adapter_config.get("r") == lora["rank"],
        "alpha": adapter_config.get("lora_alpha") == lora["alpha"],
        "target_modules": set(adapter_config.get("target_modules") or ())
        == set(lora["target_modules"]),
        "modules_to_save": adapter_config.get("modules_to_save") is None,
        "trainable_token_indices": adapter_config.get("trainable_token_indices") is None,
        "bias": adapter_config.get("bias") == "none",
        "use_dora": adapter_config.get("use_dora") is False,
        "use_rslora": adapter_config.get("use_rslora") is False,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise TrainingRunError(
            "adapter is incompatible with GGUF export: " + ", ".join(failed)
        )
    weights_path = adapter_path / "adapter_model.safetensors"
    with safe_open(weights_path, framework="pt", device="cpu") as weights:
        keys = sorted(weights.keys())
    if not keys:
        raise TrainingRunError("adapter Safetensors contains no tensors")
    forbidden = [
        key
        for key in keys
        if "embed_tokens" in key or "lm_head" in key or "lora_embedding" in key
    ]
    if forbidden:
        raise TrainingRunError("adapter contains unsupported embeddings or lm_head tensors")
    unexpected = [
        key
        for key in keys
        if not (key.endswith(".lora_A.weight") or key.endswith(".lora_B.weight"))
    ]
    if unexpected:
        raise TrainingRunError("adapter contains non-LoRA tensors")
    allowed_modules = set(lora["target_modules"])
    unsupported_targets = [
        key
        for key in keys
        if not any(f".{module}.lora_" in key for module in allowed_modules)
    ]
    if unsupported_targets:
        raise TrainingRunError("adapter contains unsupported target modules")
    pairs: dict[str, set[str]] = {}
    for key in keys:
        if key.endswith(".lora_A.weight"):
            pairs.setdefault(key.removesuffix(".lora_A.weight"), set()).add("A")
        else:
            pairs.setdefault(key.removesuffix(".lora_B.weight"), set()).add("B")
    incomplete = sorted(name for name, members in pairs.items() if members != {"A", "B"})
    if incomplete:
        raise TrainingRunError("adapter contains incomplete LoRA A/B tensor pairs")
    return {
        "checks": checks,
        "tensor_count": len(keys),
        "tensor_pair_count": len(pairs),
        "target_modules": sorted(allowed_modules),
        "weights_sha256": sha256_file(weights_path),
    }


def export_adapter_to_gguf(
    config: Mapping[str, Any],
    *,
    adapter_path: Path,
    training_report_path: Path,
    selection_report_path: Path,
    output_dir: Path,
    llama_cpp_dir: Path,
    base_model_dir: Path,
) -> dict[str, Any]:
    adapter_path = adapter_path.resolve()
    training_report_path = training_report_path.resolve()
    selection_report_path = selection_report_path.resolve()
    output_dir = output_dir.resolve()
    llama_cpp_dir = llama_cpp_dir.resolve()
    base_model_dir = base_model_dir.resolve()
    if output_dir.exists():
        raise TrainingRunError(f"immutable export destination already exists: {output_dir}")
    export_config = config.get("export")
    if not isinstance(export_config, Mapping):
        raise TrainingRunError("training config does not define an export contract")
    training_report = _load_json(training_report_path)
    selection_report = _load_json(selection_report_path)
    adapter_id = str(training_report.get("adapter_id", ""))
    if training_report.get("passed") is not True or not adapter_id:
        raise TrainingRunError("training report must pass and identify an adapter")
    if selection_report.get("selected_adapter_id") != adapter_id:
        raise TrainingRunError("selection report does not identify the requested adapter")
    if selection_report.get("held_out_selection_eligible") is not True:
        raise TrainingRunError("adapter did not pass development held-out selection")
    if training_report.get("base_model_revision") != config["base_model"]["revision"]:
        raise TrainingRunError("training report base revision does not match export config")
    compatibility = validate_peft_export_compatibility(config, adapter_path)

    converter = llama_cpp_dir / str(export_config["converter_path"])
    if not converter.is_file():
        raise TrainingRunError(f"pinned converter is missing: {converter}")
    revision_result = subprocess.run(
        ["git", "-C", str(llama_cpp_dir), "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    actual_revision = revision_result.stdout.strip()
    if revision_result.returncode != 0 or actual_revision != export_config["llama_cpp_revision"]:
        raise TrainingRunError(
            f"llama.cpp revision mismatch: expected {export_config['llama_cpp_revision']}; "
            f"found {actual_revision or 'unavailable'}"
        )
    required_base_files = ("config.json", *TOKENIZER_FILES)
    missing_base = [name for name in required_base_files if not (base_model_dir / name).is_file()]
    if missing_base:
        raise TrainingRunError("base compatibility files are missing: " + ", ".join(missing_base))

    temporary = output_dir.with_name(f".{output_dir.name}.tmp-{os.getpid()}")
    if temporary.exists():
        raise TrainingRunError(f"temporary export destination already exists: {temporary}")
    temporary.mkdir(parents=True)
    try:
        shutil.copy2(adapter_path / "adapter_config.json", temporary / "adapter_config.json")
        shutil.copy2(
            adapter_path / "adapter_model.safetensors",
            temporary / "adapter_model.safetensors",
        )
        template_source = Path(config["prompt_contract"]["chat_template_path"])
        shutil.copy2(template_source, temporary / "chat_template.jinja")
        shutil.copy2(base_model_dir / "config.json", temporary / "base_config.json")
        for filename in TOKENIZER_FILES:
            shutil.copy2(base_model_dir / filename, temporary / filename)

        gguf_name = f"{adapter_id}-{export_config['gguf_output_type']}.gguf"
        gguf_path = temporary / gguf_name
        environment = os.environ.copy()
        environment.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        conversion = subprocess.run(
            [
                sys.executable,
                str(converter),
                "--base",
                str(base_model_dir),
                "--outfile",
                str(gguf_path),
                "--outtype",
                str(export_config["gguf_output_type"]),
                str(temporary),
            ],
            cwd=llama_cpp_dir,
            capture_output=True,
            check=False,
            text=True,
            timeout=300,
            env=environment,
        )
        if conversion.returncode != 0:
            detail = (conversion.stderr or conversion.stdout).strip()[-4000:]
            raise TrainingRunError(f"PEFT-to-GGUF conversion failed: {detail}")
        if not gguf_path.is_file() or gguf_path.read_bytes()[:4] != b"GGUF":
            raise TrainingRunError("converter did not produce a valid GGUF header")

        files = {
            item.name: {
                "sha256": sha256_file(item),
                "size_bytes": item.stat().st_size,
            }
            for item in sorted(temporary.iterdir())
            if item.is_file() and item.name != "manifest.json"
        }
        manifest = {
            "schema_version": "1.0",
            "report_type": "adapter_export",
            "generated_at": datetime.now(UTC).isoformat(),
            "adapter_id": adapter_id,
            "held_out_selection_eligible": True,
            "promotion_eligible": False,
            "base_model": {
                "repo_id": config["base_model"]["repo_id"],
                "revision": config["base_model"]["revision"],
                "accepted_runtime_model": config["base_model"]["accepted_runtime_model"],
                "accepted_runtime_revision": config["base_model"][
                    "accepted_runtime_revision"
                ],
                "accepted_runtime_file_sha256": config["base_model"][
                    "accepted_runtime_file_sha256"
                ],
            },
            "prompt_contract": config["prompt_contract"],
            "adapter_compatibility": compatibility,
            "runtime": {
                "llama_cpp_revision": actual_revision,
                "converter_sha256": sha256_file(converter),
                "gguf_output_type": export_config["gguf_output_type"],
                "adapter_scale": export_config["runtime_adapter_scale"],
                "gguf_file": gguf_name,
            },
            "source_evidence": {
                "training_report_sha256": sha256_file(training_report_path),
                "selection_report_sha256": sha256_file(selection_report_path),
            },
            "files": files,
        }
        write_json_report(manifest, temporary / "manifest.json")
        temporary.rename(output_dir)
        return manifest
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
