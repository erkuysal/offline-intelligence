from __future__ import annotations

import hashlib
import json
import math
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from training.data_contract import (
    DatasetAnalysis,
    TrainingDataset,
    analyze_training_dataset,
    load_training_dataset,
)
from training.foundation import get_hugging_face_token, write_json_report


IGNORE_INDEX = -100
ADAPTER_FILES = frozenset({"adapter_config.json", "adapter_model.safetensors"})


class TrainingRunError(ValueError):
    """Raised when a bounded training run violates its reproducibility contract."""


class ChatTokenizer(Protocol):
    pad_token_id: int | None

    def apply_chat_template(
        self,
        conversation: list[Mapping[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> Any: ...


@dataclass(frozen=True)
class EncodedTrainingExample:
    input_ids: tuple[int, ...]
    attention_mask: tuple[int, ...]
    labels: tuple[int, ...]


def _input_ids(value: Any) -> list[int]:
    if isinstance(value, Mapping):
        value = value.get("input_ids")
    if not isinstance(value, list) or not all(isinstance(item, int) for item in value):
        raise TrainingRunError("chat template returned invalid input_ids")
    return value


def encode_assistant_only(
    tokenizer: ChatTokenizer,
    messages: Sequence[Mapping[str, str]],
    *,
    max_sequence_length: int,
) -> EncodedTrainingExample:
    """Render one conversation and expose loss only on assistant completion tokens."""
    if max_sequence_length <= 0:
        raise TrainingRunError("max_sequence_length must be positive")
    full_ids = _input_ids(
        tokenizer.apply_chat_template(
            list(messages), tokenize=True, add_generation_prompt=False
        )
    )
    labels = [IGNORE_INDEX] * len(full_ids)
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        prefix = list(messages[:index])
        completion_start = _input_ids(
            tokenizer.apply_chat_template(
                prefix, tokenize=True, add_generation_prompt=True
            )
        )
        completion_end = _input_ids(
            tokenizer.apply_chat_template(
                list(messages[: index + 1]),
                tokenize=True,
                add_generation_prompt=False,
            )
        )
        start = len(completion_start)
        end = len(completion_end)
        if full_ids[:start] != completion_start or full_ids[:end] != completion_end:
            raise TrainingRunError("chat template is not prefix-stable for assistant masking")
        labels[start:end] = full_ids[start:end]
    if all(label == IGNORE_INDEX for label in labels):
        raise TrainingRunError("conversation produced no assistant completion tokens")
    if len(full_ids) > max_sequence_length:
        raise TrainingRunError(
            f"rendered sequence has {len(full_ids)} tokens; maximum is {max_sequence_length}"
        )
    pad_token_id = tokenizer.pad_token_id
    if pad_token_id is None:
        raise TrainingRunError("tokenizer must define pad_token_id")
    padding = max_sequence_length - len(full_ids)
    return EncodedTrainingExample(
        input_ids=tuple(full_ids + [pad_token_id] * padding),
        attention_mask=tuple([1] * len(full_ids) + [0] * padding),
        labels=tuple(labels + [IGNORE_INDEX] * padding),
    )


def build_run_manifest(
    config: Mapping[str, Any],
    dataset: TrainingDataset,
    analysis: DatasetAnalysis,
    *,
    rank: int | None = None,
    learning_rate: float | None = None,
) -> dict[str, Any]:
    training = config["training"]
    lora = dict(training["lora"])
    optimizer = dict(training["optimizer"])
    selected_rank = lora["rank"] if rank is None else rank
    selected_learning_rate = (
        optimizer["learning_rate"] if learning_rate is None else learning_rate
    )
    if selected_rank not in training["search"]["ranks"]:
        raise TrainingRunError(f"rank {selected_rank} is outside the bounded search")
    if selected_learning_rate not in training["search"]["learning_rates"]:
        raise TrainingRunError(
            f"learning rate {selected_learning_rate} is outside the bounded search"
        )
    lora["rank"] = selected_rank
    optimizer["learning_rate"] = selected_learning_rate
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": config["experiment_id"],
        "base_model": {
            "repo_id": config["base_model"]["repo_id"],
            "revision": config["base_model"]["revision"],
        },
        "dataset": {
            "dataset_id": dataset.manifest.dataset_id,
            "dataset_version": dataset.manifest.dataset_version,
            "examples_sha256": dataset.manifest.examples_sha256,
            "dataset_checksum": analysis.dataset_checksum,
            "split_checksum": analysis.split_checksum,
        },
        "prompt_contract": dict(config["prompt_contract"]),
        "environment": dict(config["environment"]),
        "seed": training["seed"],
        "precision": training["precision"],
        "fallback_precision": training["fallback_precision"],
        "micro_batch_size": training["micro_batch_size"],
        "gradient_accumulation_steps": training["gradient_accumulation_steps"],
        "gradient_checkpointing": training["gradient_checkpointing"],
        "attention_implementation": training["attention_implementation"],
        "deterministic_algorithms": training["deterministic_algorithms"],
        "sequence_length": training["approved_max_sequence_length"],
        "epochs": training["epochs"],
        "max_steps": training["max_steps"],
        "max_gradient_norm": training["max_gradient_norm"],
        "evaluation_steps": training["evaluation_steps"],
        "checkpoint_steps": training["checkpoint_steps"],
        "optimizer": optimizer,
        "scheduler": dict(training["scheduler"]),
        "lora": lora,
    }
    manifest["run_fingerprint"] = manifest_fingerprint(manifest)
    return manifest


def manifest_fingerprint(manifest: Mapping[str, Any]) -> str:
    content = {key: value for key, value in manifest.items() if key != "run_fingerprint"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def validate_resume_manifest(
    expected: Mapping[str, Any], checkpoint_manifest_path: Path
) -> Mapping[str, Any]:
    try:
        actual = json.loads(checkpoint_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingRunError(f"could not read checkpoint manifest: {exc}") from exc
    if actual != expected:
        raise TrainingRunError("checkpoint manifest does not exactly match the requested run")
    if actual.get("run_fingerprint") != manifest_fingerprint(actual):
        raise TrainingRunError("checkpoint manifest fingerprint is invalid")
    return actual


def validate_step_numerics(loss: float, gradient_norm: float) -> None:
    if not math.isfinite(loss):
        raise TrainingRunError(f"non-finite loss detected: {loss}")
    if not math.isfinite(gradient_norm) or gradient_norm < 0:
        raise TrainingRunError(f"invalid gradient norm detected: {gradient_norm}")


def validate_adapter_checkpoint(path: Path) -> None:
    if not path.is_dir():
        raise TrainingRunError(f"adapter checkpoint directory does not exist: {path}")
    files = {item.name for item in path.iterdir() if item.is_file()}
    missing = ADAPTER_FILES - files
    forbidden = {name for name in files if name.startswith("model-") or name == "model.safetensors"}
    if missing:
        raise TrainingRunError(f"adapter checkpoint is missing: {', '.join(sorted(missing))}")
    if forbidden:
        raise TrainingRunError("checkpoint contains base-model weights")


def select_candidate_by_held_out_metrics(
    candidates: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if not candidates:
        raise TrainingRunError("at least one candidate is required")
    for candidate in candidates:
        if "training_loss" in candidate and "held_out" not in candidate:
            raise TrainingRunError("candidate selection cannot use training loss alone")
        held_out = candidate.get("held_out")
        if not isinstance(held_out, Mapping):
            raise TrainingRunError("every candidate requires held-out behavior metrics")
        if not isinstance(held_out.get("threshold_failures"), int):
            raise TrainingRunError("held-out threshold_failures must be an integer")
        if not isinstance(held_out.get("behavior_score"), (int, float)):
            raise TrainingRunError("held-out behavior_score must be numeric")
    return min(
        candidates,
        key=lambda item: (
            item["held_out"]["threshold_failures"],
            -float(item["held_out"]["behavior_score"]),
            str(item.get("adapter_id", "")),
        ),
    )


def _load_tokenizer(config: Mapping[str, Any], *, local_files_only: bool) -> Any:
    try:
        from transformers import AutoTokenizer  # type: ignore[import-not-found]
    except (ImportError, OSError) as exc:
        raise TrainingRunError("training requires the pinned transformers package") from exc
    template_path = Path(config["prompt_contract"]["chat_template_path"])
    try:
        template = template_path.read_text(encoding="utf-8")
        if hashlib.sha256(template.encode()).hexdigest() != config["prompt_contract"][
            "chat_template_sha256"
        ]:
            raise TrainingRunError("chat template checksum does not match the run contract")
        tokenizer = AutoTokenizer.from_pretrained(
            config["base_model"]["repo_id"],
            revision=config["base_model"]["revision"],
            token=get_hugging_face_token(),
            local_files_only=local_files_only,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise TrainingRunError(f"could not load the pinned tokenizer: {exc}") from exc
    tokenizer.chat_template = template
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    return tokenizer


def _mean_validation_loss(model: Any, examples: Sequence[EncodedTrainingExample], torch: Any) -> float:
    if not examples:
        raise TrainingRunError("validation split is empty")
    losses: list[float] = []
    model.eval()
    with torch.no_grad():
        for example in examples:
            active_length = sum(example.attention_mask)
            loss = model(
                input_ids=torch.tensor([example.input_ids[:active_length]], device="cuda"),
                attention_mask=torch.tensor([example.attention_mask[:active_length]], device="cuda"),
                labels=torch.tensor([example.labels[:active_length]], device="cuda"),
            ).loss
            value = float(loss.detach().cpu())
            validate_step_numerics(value, 0.0)
            losses.append(value)
    model.train()
    return sum(losses) / len(losses)


def _save_checkpoint(
    model: Any,
    optimizer: Any,
    scheduler: Any,
    manifest: Mapping[str, Any],
    *,
    output: Path,
    step: int,
    epoch: int,
    next_example_position: int,
    example_order: Sequence[int],
    metrics: Mapping[str, Any],
    torch: Any,
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    model.save_pretrained(output, safe_serialization=True)
    write_json_report(manifest, output / "run-manifest.json")
    torch.save(
        {
            "step": step,
            "epoch": epoch,
            "next_example_position": next_example_position,
            "example_order": list(example_order),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
            "python_random_state": random.getstate(),
            "torch_random_state": torch.get_rng_state(),
            "cuda_random_state": torch.cuda.get_rng_state_all(),
            "metrics": dict(metrics),
        },
        output / "training-state.pt",
    )
    validate_adapter_checkpoint(output)


def run_bounded_training(
    config: Mapping[str, Any],
    *,
    manifest_path: Path,
    output_dir: Path,
    rank: int | None = None,
    learning_rate: float | None = None,
    resume_from: Path | None = None,
    local_files_only: bool = True,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Execute one bounded, reproducible LoRA candidate run on CUDA."""
    try:
        import torch  # type: ignore[import-not-found]
        from peft import LoraConfig, PeftModel, get_peft_model  # type: ignore[import-not-found]
        from transformers import (  # type: ignore[import-not-found]
            AutoModelForCausalLM,
            get_scheduler,
        )
    except (ImportError, OSError) as exc:
        raise TrainingRunError("training requires the pinned offline-ai-training environment") from exc
    if not torch.cuda.is_available():
        raise TrainingRunError("bounded training requires a CUDA device visible to PyTorch")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise TrainingRunError(f"output directory is not empty: {output_dir}")

    tokenizer = _load_tokenizer(config, local_files_only=local_files_only)
    dataset = load_training_dataset(
        manifest_path, **({"config_path": config_path} if config_path is not None else {})
    )

    def count_tokens(messages: Sequence[Mapping[str, str]]) -> int:
        return len(
            _input_ids(
                tokenizer.apply_chat_template(
                    list(messages), tokenize=True, add_generation_prompt=False
                )
            )
        )

    analysis = analyze_training_dataset(dataset, token_counter=count_tokens)
    run_manifest = build_run_manifest(
        config, dataset, analysis, rank=rank, learning_rate=learning_rate
    )
    maximum_length = run_manifest["sequence_length"]
    encoded_by_split: dict[str, list[EncodedTrainingExample]] = {
        "train": [],
        "validation": [],
        "held_out": [],
    }
    for example in dataset.examples:
        split = analysis.assignments[example.example_id]
        encoded_by_split[split].append(
            encode_assistant_only(
                tokenizer, example.messages, max_sequence_length=maximum_length
            )
        )
    train_examples = encoded_by_split["train"]
    validation_examples = encoded_by_split["validation"]
    if not train_examples:
        raise TrainingRunError("training split is empty")
    if not validation_examples:
        raise TrainingRunError("validation split is empty")

    seed = run_manifest["seed"]
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(
        run_manifest["deterministic_algorithms"], warn_only=False
    )
    precision = run_manifest["precision"]
    if precision == "bf16" and torch.cuda.is_bf16_supported():
        dtype = torch.bfloat16
    else:
        precision = run_manifest["fallback_precision"]
        dtype = torch.float16
    try:
        base_model = AutoModelForCausalLM.from_pretrained(
            run_manifest["base_model"]["repo_id"],
            revision=run_manifest["base_model"]["revision"],
            token=get_hugging_face_token(),
            local_files_only=local_files_only,
            dtype=dtype,
            attn_implementation=run_manifest["attention_implementation"],
        )
        base_model.config.use_cache = False
        if run_manifest["gradient_checkpointing"]:
            base_model.gradient_checkpointing_enable()
        if resume_from is None:
            lora = run_manifest["lora"]
            model = get_peft_model(
                base_model,
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
            )
        else:
            validate_resume_manifest(run_manifest, resume_from / "run-manifest.json")
            validate_adapter_checkpoint(resume_from)
            model = PeftModel.from_pretrained(base_model, resume_from, is_trainable=True)
        model = model.to("cuda")
        optimizer_config = run_manifest["optimizer"]
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
        accumulation = run_manifest["gradient_accumulation_steps"]
        updates_per_epoch = math.ceil(len(train_examples) / accumulation)
        total_steps = min(run_manifest["max_steps"], run_manifest["epochs"] * updates_per_epoch)
        scheduler_config = run_manifest["scheduler"]
        warmup_steps = (
            scheduler_config["warmup_steps"]
            if "warmup_steps" in scheduler_config
            else math.floor(total_steps * scheduler_config["warmup_ratio"])
        )
        if warmup_steps >= total_steps:
            raise TrainingRunError("scheduler warmup_steps must be below total optimizer steps")
        scheduler = get_scheduler(
            scheduler_config["name"],
            optimizer,
            num_warmup_steps=warmup_steps,
            num_training_steps=total_steps,
            scheduler_specific_kwargs={},
        )
        start_step = 0
        start_epoch = 0
        resume_position = 0
        resume_order: list[int] | None = None
        prior_duration = 0.0
        trained_tokens = 0
        losses: list[float] = []
        gradient_norms: list[float] = []
        validation_losses: list[dict[str, float | int]] = []
        if resume_from is not None:
            state = torch.load(
                resume_from / "training-state.pt", map_location="cpu", weights_only=False
            )
            optimizer.load_state_dict(state["optimizer"])
            scheduler.load_state_dict(state["scheduler"])
            random.setstate(state["python_random_state"])
            torch.set_rng_state(state["torch_random_state"])
            torch.cuda.set_rng_state_all(state["cuda_random_state"])
            start_step = int(state["step"])
            start_epoch = int(state["epoch"])
            resume_position = int(state["next_example_position"])
            resume_order = [int(index) for index in state["example_order"]]
            if sorted(resume_order) != list(range(len(train_examples))):
                raise TrainingRunError("checkpoint example order does not match the training split")
            if not 0 <= resume_position <= len(resume_order):
                raise TrainingRunError("checkpoint example position is invalid")
            metrics = state.get("metrics")
            if not isinstance(metrics, dict):
                raise TrainingRunError("checkpoint metrics state is missing")
            losses = [float(value) for value in metrics["training_loss"]]
            gradient_norms = [float(value) for value in metrics["gradient_norms"]]
            validation_losses = list(metrics["validation_loss"])
            trained_tokens = int(metrics["assistant_tokens"])
            prior_duration = float(metrics["wall_clock_seconds"])
            if start_step >= total_steps:
                raise TrainingRunError("checkpoint already reached the configured step bound")

        output_dir.mkdir(parents=True, exist_ok=True)
        write_json_report(run_manifest, output_dir / "run-manifest.json")
        torch.cuda.reset_peak_memory_stats()
        optimizer.zero_grad(set_to_none=True)
        started = time.perf_counter()
        step = start_step
        accumulated_losses: list[float] = []
        for epoch in range(start_epoch, run_manifest["epochs"]):
            if epoch == start_epoch and resume_order is not None:
                order = resume_order
                position = resume_position
                resume_order = None
            else:
                order = list(range(len(train_examples)))
                random.shuffle(order)
                position = 0
            for micro_step, example_index in enumerate(
                order[position:], start=position + 1
            ):
                encoded_example = train_examples[example_index]
                active_length = sum(encoded_example.attention_mask)
                outputs = model(
                    input_ids=torch.tensor(
                        [encoded_example.input_ids[:active_length]], device="cuda"
                    ),
                    attention_mask=torch.tensor(
                        [encoded_example.attention_mask[:active_length]], device="cuda"
                    ),
                    labels=torch.tensor(
                        [encoded_example.labels[:active_length]], device="cuda"
                    ),
                )
                raw_loss = outputs.loss
                loss_value = float(raw_loss.detach().cpu())
                validate_step_numerics(loss_value, 0.0)
                group_start = ((micro_step - 1) // accumulation) * accumulation
                group_size = min(accumulation, len(order) - group_start)
                (raw_loss / group_size).backward()
                accumulated_losses.append(loss_value)
                trained_tokens += sum(label != IGNORE_INDEX for label in encoded_example.labels)
                is_update = micro_step % accumulation == 0 or micro_step == len(order)
                if not is_update:
                    continue
                gradient_norm = torch.nn.utils.clip_grad_norm_(
                    model.parameters(), run_manifest["max_gradient_norm"]
                )
                gradient_value = float(gradient_norm.detach().cpu())
                validate_step_numerics(loss_value, gradient_value)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
                step += 1
                update_loss = sum(accumulated_losses) / len(accumulated_losses)
                losses.append(update_loss)
                accumulated_losses = []
                gradient_norms.append(gradient_value)
                if step % run_manifest["evaluation_steps"] == 0 or step == total_steps:
                    validation_losses.append(
                        {
                            "step": step,
                            "loss": _mean_validation_loss(
                                model, validation_examples, torch
                            ),
                        }
                    )
                if step % run_manifest["checkpoint_steps"] == 0 and step < total_steps:
                    _save_checkpoint(
                        model,
                        optimizer,
                        scheduler,
                        run_manifest,
                        output=output_dir / f"checkpoint-{step:06d}",
                        step=step,
                        epoch=epoch,
                        next_example_position=micro_step,
                        example_order=order,
                        metrics={
                            "training_loss": losses,
                            "gradient_norms": gradient_norms,
                            "validation_loss": validation_losses,
                            "assistant_tokens": trained_tokens,
                            "wall_clock_seconds": prior_duration
                            + time.perf_counter()
                            - started,
                        },
                        torch=torch,
                    )
                if step >= total_steps:
                    break
            if step >= total_steps:
                break
        torch.cuda.synchronize()
        duration = prior_duration + time.perf_counter() - started
        final_adapter = output_dir / "adapter"
        model.save_pretrained(final_adapter, safe_serialization=True)
        validate_adapter_checkpoint(final_adapter)
    except torch.OutOfMemoryError as exc:
        raise TrainingRunError("CUDA out of memory; run stopped without relaxing the contract") from exc

    adapter_id = (
        f"{run_manifest['experiment_id']}-r{run_manifest['lora']['rank']}-"
        f"lr{run_manifest['optimizer']['learning_rate']:g}-{run_manifest['run_fingerprint'][:12]}"
    )
    report = {
        "schema_version": "1.0",
        "report_type": "training_run",
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "adapter_id": adapter_id,
        "run_fingerprint": run_manifest["run_fingerprint"],
        "run_manifest": run_manifest,
        "dataset_id": dataset.manifest.dataset_id,
        "dataset_version": dataset.manifest.dataset_version,
        "dataset_checksum": analysis.dataset_checksum,
        "base_model_revision": run_manifest["base_model"]["revision"],
        "precision": precision,
        "completed_steps": step,
        "training_loss": losses,
        "validation_loss": validation_losses,
        "gradient_norms": gradient_norms,
        "peak_allocated_mib": round(torch.cuda.max_memory_allocated() / (1024**2), 3),
        "peak_reserved_mib": round(torch.cuda.max_memory_reserved() / (1024**2), 3),
        "assistant_tokens": trained_tokens,
        "tokens_per_second": round(trained_tokens / duration, 3),
        "wall_clock_seconds": round(duration, 3),
        "adapter_path": str(final_adapter),
        "candidate_selection_eligible": False,
        "candidate_selection_note": "held-out behavior evidence is required",
    }
    write_json_report(report, output_dir / "training-report.json")
    return report
