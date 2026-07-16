from __future__ import annotations

import json
import re
import time
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from training.data_contract import analyze_training_dataset, load_training_dataset
from training.foundation import get_hugging_face_token, write_json_report
from training.trainer import TrainingRunError, _input_ids, _load_tokenizer


def normalize_words(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.findall(r"\w+", normalized, flags=re.UNICODE)


def token_f1(generated: str, expected: str) -> float:
    generated_words = normalize_words(generated)
    expected_words = normalize_words(expected)
    if not generated_words or not expected_words:
        return 0.0
    generated_counts = {word: generated_words.count(word) for word in set(generated_words)}
    expected_counts = {word: expected_words.count(word) for word in set(expected_words)}
    overlap = sum(
        min(count, expected_counts.get(word, 0)) for word, count in generated_counts.items()
    )
    if overlap == 0:
        return 0.0
    precision = overlap / len(generated_words)
    recall = overlap / len(expected_words)
    return 2 * precision * recall / (precision + recall)


def language_adherent(answer: str, language: str) -> bool:
    words = set(normalize_words(answer))
    en = {"the", "is", "and", "at", "owned", "information", "source"}
    tr = {"bu", "ve", "saat", "tarafından", "bilgi", "kaynakta", "için"}
    if language == "tr" and words & {"hizmet", "çalışma_saati", "sorumlu", "durum"}:
        return True
    if language == "en" and words & {"service", "run_window", "owner", "status"}:
        return True
    expected_markers = tr if language == "tr" else en
    other_markers = en if language == "tr" else tr
    if language == "en" and not words & other_markers:
        return True
    return len(words & expected_markers) >= 1 and not (
        len(words & other_markers) > len(words & expected_markers)
    )


def score_behavior(
    *,
    task: str,
    language: str,
    answer: str,
    expected: str,
    expected_citations: Sequence[Mapping[str, str]],
    target_json_schema: Mapping[str, Any] | None,
    user_prompt: str,
) -> dict[str, Any]:
    scores: dict[str, Any] = {
        "token_f1": round(token_f1(answer, expected), 6),
        "language_adherent": language_adherent(answer, language),
    }
    if task in {"grounded_answer", "citation_formatting"}:
        markers = [
            f"[{item['source_id']}#{item['passage_id']}]"
            if item.get("passage_id")
            else f"[{item['source_id']}]"
            for item in expected_citations
        ]
        scores["task_valid"] = bool(markers) and all(marker in answer for marker in markers)
    elif task == "grounded_refusal":
        refusal_phrases = (
            "do not have enough information",
            "don't have enough information",
            "cannot answer",
            "do not have access",
            "yeterli bilgi bulunmuyor",
            "yeterli bilgi yok",
            "cevabı verilmedi",
        )
        scores["task_valid"] = any(phrase in answer.casefold() for phrase in refusal_phrases)
    elif task == "json_output":
        try:
            payload = json.loads(answer)
        except json.JSONDecodeError:
            scores["task_valid"] = False
        else:
            required = target_json_schema.get("required", []) if target_json_schema else []
            properties = target_json_schema.get("properties", {}) if target_json_schema else {}
            enum_valid = isinstance(payload, dict) and all(
                not definition.get("enum") or payload.get(key) in definition["enum"]
                for key, definition in properties.items()
            )
            scores["task_valid"] = (
                isinstance(payload, dict) and set(payload) == set(required) and enum_valid
            )
    elif task == "incident_report":
        headings = (
            ("Özet:", "Etki:", "Neden:", "Eylem:")
            if language == "tr"
            else ("Summary:", "Impact:", "Cause:", "Action:")
        )
        normalized_answer = re.sub(r"[*#_]", "", answer).casefold()
        scores["task_valid"] = all(
            heading.casefold() in normalized_answer for heading in headings
        )
    else:
        quoted = re.findall(r"'([^']+)'", user_prompt)
        required = quoted[0] if quoted else ""
        forbidden = next(
            (value for value in reversed(quoted[1:]) if value.casefold() != required.casefold()),
            "",
        )
        scores["task_valid"] = bool(required) and required.casefold() in answer.casefold() and (
            not forbidden or forbidden.casefold() not in answer.casefold()
        )
    return scores


def run_candidate_evaluation(
    config: Mapping[str, Any],
    *,
    manifest_path: Path,
    adapter_path: Path,
    training_report_path: Path,
    output: Path,
    local_files_only: bool = True,
    max_new_tokens: int = 192,
) -> dict[str, Any]:
    try:
        import torch  # type: ignore[import-not-found]
        from peft import PeftModel  # type: ignore[import-not-found]
        from transformers import AutoModelForCausalLM  # type: ignore[import-not-found]
    except (ImportError, OSError) as exc:
        raise TrainingRunError("candidate evaluation requires offline-ai-training") from exc
    if not torch.cuda.is_available():
        raise TrainingRunError("candidate evaluation requires CUDA")
    training_report = json.loads(training_report_path.read_text(encoding="utf-8"))
    if training_report.get("passed") is not True:
        raise TrainingRunError("training report must pass")
    tokenizer = _load_tokenizer(config, local_files_only=local_files_only)
    dataset = load_training_dataset(manifest_path)

    def count_tokens(messages: Sequence[Mapping[str, str]]) -> int:
        return len(_input_ids(tokenizer.apply_chat_template(list(messages), tokenize=True, add_generation_prompt=False)))

    analysis = analyze_training_dataset(dataset, token_counter=count_tokens)
    if training_report.get("dataset_checksum") != analysis.dataset_checksum:
        raise TrainingRunError("training report dataset checksum does not match held-out dataset")
    held_out = [example for example in dataset.examples if analysis.assignments[example.example_id] == "held_out"]
    if not held_out:
        raise TrainingRunError("held-out split is empty")
    torch.use_deterministic_algorithms(True, warn_only=False)
    torch.manual_seed(config["training"]["seed"])
    torch.cuda.manual_seed_all(config["training"]["seed"])
    base = AutoModelForCausalLM.from_pretrained(
        config["base_model"]["repo_id"],
        revision=config["base_model"]["revision"],
        token=get_hugging_face_token(),
        local_files_only=local_files_only,
        dtype=torch.bfloat16,
        attn_implementation=config["training"]["attention_implementation"],
    )
    model = PeftModel.from_pretrained(base, adapter_path).to("cuda").eval()
    cases: list[dict[str, Any]] = []
    started = time.perf_counter()
    for example in held_out:
        prompt_messages = list(example.messages[:-1])
        input_ids = _input_ids(tokenizer.apply_chat_template(prompt_messages, tokenize=True, add_generation_prompt=True))
        tensor = torch.tensor([input_ids], device="cuda")
        with torch.no_grad():
            output_ids = model.generate(
                input_ids=tensor,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                use_cache=True,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )[0, len(input_ids) :]
        answer = tokenizer.decode(output_ids, skip_special_tokens=True).strip()
        scores = score_behavior(
            task=example.task,
            language=example.language,
            answer=answer,
            expected=example.messages[-1]["content"],
            expected_citations=example.expected_citations,
            target_json_schema=example.target_json_schema,
            user_prompt=example.messages[-2]["content"],
        )
        cases.append(
            {
                "example_id": example.example_id,
                "task": example.task,
                "language": example.language,
                "answer": answer,
                **scores,
            }
        )
    slices: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        slices[f"task:{case['task']}"].append(case)
        slices[f"language:{case['language']}"].append(case)
    summary = {
        key: {
            "case_count": len(values),
            "mean_token_f1": round(sum(item["token_f1"] for item in values) / len(values), 6),
            "language_adherence": round(sum(item["language_adherent"] for item in values) / len(values), 6),
            "task_validity": round(sum(item["task_valid"] for item in values) / len(values), 6),
        }
        for key, values in sorted(slices.items())
    }
    mean_f1 = sum(case["token_f1"] for case in cases) / len(cases)
    language_rate = sum(case["language_adherent"] for case in cases) / len(cases)
    validity_rate = sum(case["task_valid"] for case in cases) / len(cases)
    failures: list[str] = []
    if mean_f1 < 0.5:
        failures.append(f"mean_token_f1 {mean_f1:.3f} < 0.500")
    if language_rate < 0.9:
        failures.append(f"language_adherence {language_rate:.3f} < 0.900")
    if validity_rate < 0.8:
        failures.append(f"task_validity {validity_rate:.3f} < 0.800")
    for key, values in summary.items():
        if key.startswith("task:") and values["task_validity"] < 0.5:
            failures.append(f"{key} task_validity {values['task_validity']:.3f} < 0.500")
    report = {
        "schema_version": "1.0",
        "report_type": "training_framework_held_out_behavior",
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": not failures,
        "adapter_id": training_report["adapter_id"],
        "dataset_id": dataset.manifest.dataset_id,
        "dataset_version": dataset.manifest.dataset_version,
        "dataset_checksum": analysis.dataset_checksum,
        "split_checksum": analysis.split_checksum,
        "case_count": len(cases),
        "metrics": {
            "mean_token_f1": round(mean_f1, 6),
            "language_adherence": round(language_rate, 6),
            "task_validity": round(validity_rate, 6),
            "behavior_score": round((mean_f1 + language_rate + validity_rate) / 3, 6),
        },
        "slices": summary,
        "threshold_failures": failures,
        "wall_clock_seconds": round(time.perf_counter() - started, 3),
        "cases": cases,
    }
    write_json_report(report, output)
    return report


def build_candidate_selection_report(
    training_report_paths: Sequence[Path],
    held_out_report_paths: Sequence[Path],
    *,
    output: Path,
) -> dict[str, Any]:
    if len(training_report_paths) != len(held_out_report_paths) or not training_report_paths:
        raise TrainingRunError("candidate selection requires paired training and held-out reports")
    candidates: list[dict[str, Any]] = []
    dataset_identity: tuple[str, str, str] | None = None
    for training_path, held_out_path in zip(
        training_report_paths, held_out_report_paths, strict=True
    ):
        training = json.loads(training_path.read_text(encoding="utf-8"))
        held_out = json.loads(held_out_path.read_text(encoding="utf-8"))
        if training.get("passed") is not True:
            raise TrainingRunError(f"training report did not pass: {training_path}")
        if training.get("adapter_id") != held_out.get("adapter_id"):
            raise TrainingRunError("training and held-out adapter identities do not match")
        identity = (
            str(held_out.get("dataset_id")),
            str(held_out.get("dataset_version")),
            str(held_out.get("dataset_checksum")),
        )
        if dataset_identity is None:
            dataset_identity = identity
        elif identity != dataset_identity:
            raise TrainingRunError("candidate held-out dataset identities do not match")
        failures = held_out.get("threshold_failures")
        metrics = held_out.get("metrics")
        if not isinstance(failures, list) or not isinstance(metrics, dict):
            raise TrainingRunError("held-out report lacks structured metrics or failures")
        candidates.append(
            {
                "adapter_id": training["adapter_id"],
                "run_fingerprint": training["run_fingerprint"],
                "rank": training["run_manifest"]["lora"]["rank"],
                "learning_rate": training["run_manifest"]["optimizer"]["learning_rate"],
                "validation_loss": training["validation_loss"][-1]["loss"],
                "behavior_score": metrics["behavior_score"],
                "threshold_failure_count": len(failures),
                "threshold_failures": failures,
                "held_out_passed": held_out.get("passed") is True,
                "training_report": str(training_path),
                "held_out_report": str(held_out_path),
            }
        )
    selected = min(
        candidates,
        key=lambda item: (
            item["threshold_failure_count"],
            -item["behavior_score"],
            item["adapter_id"],
        ),
    )
    assert dataset_identity is not None
    report = {
        "schema_version": "1.0",
        "report_type": "bounded_candidate_selection",
        "generated_at": datetime.now(UTC).isoformat(),
        "selection_policy": "fewest held-out threshold failures, then highest behavior score",
        "training_loss_used_for_selection": False,
        "dataset_id": dataset_identity[0],
        "dataset_version": dataset_identity[1],
        "dataset_checksum": dataset_identity[2],
        "candidate_count": len(candidates),
        "selected_adapter_id": selected["adapter_id"],
        "promotion_eligible": selected["held_out_passed"],
        "candidates": sorted(candidates, key=lambda item: item["adapter_id"]),
    }
    write_json_report(report, output)
    return report
