from __future__ import annotations

import gc
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from training.foundation import (
    TrainingFoundationError,
    get_hugging_face_token,
    write_json_report,
)


def run_calibration(
    config: dict[str, Any],
    *,
    output: Path,
    local_files_only: bool,
) -> dict[str, Any]:
    try:
        import torch  # type: ignore[import-not-found]
        from peft import LoraConfig, get_peft_model  # type: ignore[import-not-found]
        from transformers import AutoModelForCausalLM  # type: ignore[import-not-found]
    except (ImportError, OSError) as exc:
        raise TrainingFoundationError(
            "Calibration requires the pinned offline-ai-training environment"
        ) from exc

    if not torch.cuda.is_available():
        raise TrainingFoundationError("Calibration requires a CUDA device visible to PyTorch")

    training = config["training"]
    if training["precision"] == "bf16" and torch.cuda.is_bf16_supported():
        dtype = torch.bfloat16
        precision = "bf16"
    else:
        dtype = torch.float16
        precision = training["fallback_precision"]

    random.seed(training["seed"])
    torch.manual_seed(training["seed"])
    torch.cuda.manual_seed_all(training["seed"])
    torch.use_deterministic_algorithms(training["deterministic_algorithms"], warn_only=False)
    base_model = config["base_model"]
    token = get_hugging_face_token()
    if base_model.get("gated") and not token and not local_files_only:
        raise TrainingFoundationError(
            "A Hugging Face login or HF_TOKEN is required to download the gated base model"
        )

    model = AutoModelForCausalLM.from_pretrained(
        base_model["repo_id"],
        revision=base_model["revision"],
        token=token,
        local_files_only=local_files_only,
        dtype=dtype,
        attn_implementation=training["attention_implementation"],
    )
    model.config.use_cache = False
    if training["gradient_checkpointing"]:
        model.gradient_checkpointing_enable()

    lora = training["lora"]
    model = get_peft_model(
        model,
        LoraConfig(
            r=lora["rank"],
            lora_alpha=lora["alpha"],
            lora_dropout=lora["dropout"],
            bias=lora["bias"],
            fan_in_fan_out=lora["fan_in_fan_out"],
            init_lora_weights=lora["init_lora_weights"],
            use_rslora=lora["use_rslora"],
            use_dora=lora["use_dora"],
            target_modules=lora["target_modules"],
            task_type="CAUSAL_LM",
        ),
    ).to("cuda")
    optimizer_config = training["optimizer"]
    optimizer = torch.optim.AdamW(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=optimizer_config["learning_rate"],
        betas=tuple(optimizer_config["betas"]),
        eps=optimizer_config["epsilon"],
        weight_decay=optimizer_config["weight_decay"],
        amsgrad=optimizer_config["amsgrad"],
        maximize=optimizer_config["maximize"],
        foreach=optimizer_config["foreach"],
        capturable=optimizer_config["capturable"],
        differentiable=optimizer_config["differentiable"],
        fused=optimizer_config["fused"],
    )
    trainable_parameters = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    total_parameters = sum(parameter.numel() for parameter in model.parameters())
    vocab_size = int(model.config.vocab_size)

    results: list[dict[str, Any]] = []
    for sequence_length in training["sequence_lengths"]:
        optimizer.zero_grad(set_to_none=True)
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        input_ids = torch.randint(
            low=0,
            high=vocab_size,
            size=(training["micro_batch_size"], sequence_length),
            device="cuda",
        )
        labels = input_ids.clone()
        labels[:, : sequence_length // 2] = -100
        attention_mask = torch.ones_like(input_ids)
        torch.cuda.synchronize()
        started = time.perf_counter()
        try:
            loss = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels).loss
            loss.backward()
            optimizer.step()
            torch.cuda.synchronize()
        except torch.OutOfMemoryError as exc:
            raise TrainingFoundationError(
                f"CUDA out of memory during {sequence_length}-token calibration"
            ) from exc
        elapsed_seconds = time.perf_counter() - started
        results.append(
            {
                "sequence_length": sequence_length,
                "micro_batch_size": training["micro_batch_size"],
                "loss": float(loss.detach().cpu()),
                "step_seconds": round(elapsed_seconds, 6),
                "peak_allocated_mib": round(torch.cuda.max_memory_allocated() / (1024**2), 3),
                "peak_reserved_mib": round(torch.cuda.max_memory_reserved() / (1024**2), 3),
            }
        )
        del input_ids, labels, attention_mask, loss

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "experiment_id": config["experiment_id"],
        "base_model": base_model,
        "precision": precision,
        "gradient_checkpointing": training["gradient_checkpointing"],
        "trainable_parameters": trainable_parameters,
        "total_parameters": total_parameters,
        "trainable_parameter_fraction": trainable_parameters / total_parameters,
        "device": {
            "name": torch.cuda.get_device_name(0),
            "capability": ".".join(str(part) for part in torch.cuda.get_device_capability(0)),
            "torch_cuda_version": torch.version.cuda,
        },
        "results": results,
        "passed": len(results) == len(training["sequence_lengths"]),
    }
    write_json_report(report, output)
    return report


def format_calibration_summary(report: dict[str, Any]) -> str:
    lines = [
        f"Training calibration: {'PASS' if report['passed'] else 'FAIL'}",
        f"Device: {report['device']['name']}",
        f"Precision: {report['precision']}",
        f"Trainable parameters: {report['trainable_parameters']:,}",
    ]
    for result in report["results"]:
        lines.append(
            f"{result['sequence_length']} tokens: {result['step_seconds']:.3f}s, "
            f"peak allocated {result['peak_allocated_mib']:.1f} MiB, "
            f"reserved {result['peak_reserved_mib']:.1f} MiB"
        )
    return "\n".join(lines)
