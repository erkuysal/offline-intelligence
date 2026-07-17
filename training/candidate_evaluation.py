from __future__ import annotations

import json
import re
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
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
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", answer).casefold()
        if unicodedata.category(character) != "Mn"
    )
    normalized = " ".join(re.sub(r"[^\w%:]+", " ", normalized).split())
    if not normalized:
        return False
    words = set(normalized.split())
    english_markers = {"the", "is", "are", "and", "must", "does", "not", "within", "every"}
    turkish_markers = {"bir", "bu", "ve", "icin", "degil", "gerekir", "her", "icinde", "olarak"}
    english_score = len(words & english_markers)
    turkish_score = len(words & turkish_markers)
    has_turkish_character = bool(re.search(r"[çğıöşü]", answer.casefold()))
    if language == "tr":
        return has_turkish_character or turkish_score >= english_score
    return not has_turkish_character and english_score >= turkish_score


def _json_value_matches_schema(value: Any, schema: Mapping[str, Any]) -> bool:
    if "enum" in schema and value not in schema["enum"]:
        return False
    expected_type = schema.get("type")
    type_matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    if isinstance(expected_type, str) and not type_matches.get(expected_type, False):
        return False
    if isinstance(value, dict):
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if not isinstance(required, list) or not all(field in value for field in required):
            return False
        if not isinstance(properties, dict):
            return False
        if schema.get("additionalProperties") is False and any(
            field not in properties for field in value
        ):
            return False
        return all(
            not isinstance(properties.get(field), dict)
            or _json_value_matches_schema(field_value, properties[field])
            for field, field_value in value.items()
            if field in properties
        )
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return all(_json_value_matches_schema(item, schema["items"]) for item in value)
    return True


def score_behavior(
    *,
    task: str,
    language: str,
    answer: str,
    expected: str,
    expected_citations: Sequence[Mapping[str, str]],
    target_json_schema: Mapping[str, Any] | None,
    user_prompt: str,
    system_prompt: str = "",
) -> dict[str, Any]:
    scores: dict[str, Any] = {
        "token_f1": round(token_f1(answer, expected), 6),
        "language_adherent": language_adherent(answer, language),
    }
    if task in {"grounded_answer", "citation_formatting"}:
        markers = [
            item.get("runtime_label")
            or (
                f"[{item['source_id']}#{item['passage_id']}]"
                if item.get("passage_id")
                else f"[{item['source_id']}]"
            )
            for item in expected_citations
        ]
        source_like = re.findall(r"\[[^\]]*source[^\]]*\]", answer, flags=re.IGNORECASE)
        runtime_contract = any(item.get("runtime_label") for item in expected_citations)
        valid_runtime_labels = not runtime_contract or all(
            re.fullmatch(r"\[Source [1-9][0-9]*\]", marker) for marker in source_like
        )
        scores["task_valid"] = (
            bool(markers)
            and all(marker in answer for marker in markers)
            and valid_runtime_labels
        )
    elif task == "grounded_refusal":
        refusal_phrases = (
            "do not have enough information",
            "don't have enough information",
            "cannot answer",
            "do not have access",
            "available documents do not provide the answer",
            "documents do not provide the answer",
            "yeterli bilgi bulunmuyor",
            "yeterli bilgi yok",
            "cevabı verilmedi",
            "belgeler bu sorunun yanıtını sağlamıyor",
        )
        scores["task_valid"] = any(phrase in answer.casefold() for phrase in refusal_phrases)
    elif task == "json_output":
        payload_text = answer.strip()
        fenced = re.fullmatch(
            r"```(?:json)?\s*(.*?)\s*```",
            payload_text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if fenced:
            payload_text = fenced.group(1)
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            scores["task_valid"] = False
        else:
            scores["task_valid"] = target_json_schema is not None and (
                _json_value_matches_schema(payload, target_json_schema)
            )
    elif task == "incident_report":
        headings = (
            ("Etki:", "Zaman Çizelgesi:", "Neden:", "Eylem:")
            if language == "tr"
            else ("Impact:", "Timeline:", "Cause:", "Action:")
        )
        normalized_answer = re.sub(r"[*#_]", "", answer).casefold()
        scores["task_valid"] = all(
            heading.casefold() in normalized_answer for heading in headings
        )
    else:
        if language == "tr":
            required_match = re.search(
                r"(?:tam standart terim|tam olarak)\s*'([^']+)'",
                user_prompt,
                flags=re.IGNORECASE,
            )
            forbidden_match = re.search(
                r"'([^']+)'\s*(?:ifadesini kullanma|deme)",
                user_prompt,
                flags=re.IGNORECASE,
            )
        else:
            required_match = re.search(
                r"(?:use the )?exact canonical term\s*'([^']+)'",
                user_prompt,
                flags=re.IGNORECASE,
            )
            forbidden_match = re.search(
                r"do not use\s*'([^']+)'",
                user_prompt,
                flags=re.IGNORECASE,
            )
        required = required_match.group(1) if required_match else ""
        forbidden = forbidden_match.group(1) if forbidden_match else ""
        if not required and system_prompt:
            if language == "tr":
                contract_match = re.search(
                    r"Onaylı terim ([^;]+); ([^;]+?) ifadesi kullanımdan kaldırılmıştır",
                    system_prompt,
                    flags=re.IGNORECASE,
                )
            else:
                contract_match = re.search(
                    r"approved term is ([^;]+); ([^;]+?) is deprecated",
                    system_prompt,
                    flags=re.IGNORECASE,
                )
            if contract_match:
                required, forbidden = contract_match.groups()
        scores["task_valid"] = bool(required) and required.casefold() in answer.casefold() and (
            not forbidden or forbidden.casefold() not in answer.casefold()
        )
    return scores


def _runtime_chat_completion(
    base_url: str,
    *,
    model: str,
    messages: Sequence[Mapping[str, str]],
    max_new_tokens: int,
    seed: int,
) -> str:
    request = Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "messages": list(messages),
                "temperature": 0,
                "seed": seed,
                "max_tokens": max_new_tokens,
                "stream": False,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:  # noqa: S310 - operator-supplied local URL
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TrainingRunError(f"deployed runtime request failed: {type(exc).__name__}") from exc
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise TrainingRunError("deployed runtime returned an invalid chat completion") from exc
    if not isinstance(content, str):
        raise TrainingRunError("deployed runtime returned non-text content")
    return content.strip()


def run_deployed_candidate_evaluation(
    config: Mapping[str, Any],
    *,
    manifest_path: Path,
    training_framework_report_path: Path,
    output: Path,
    runtime_base_url: str,
    runtime_model: str,
    adapter_id: str,
    adapter_sha256: str,
    max_new_tokens: int = 192,
    config_path: Path | None = None,
) -> dict[str, Any]:
    framework = json.loads(training_framework_report_path.read_text(encoding="utf-8"))
    if framework.get("passed") is not True or framework.get("adapter_id") != adapter_id:
        raise TrainingRunError("training-framework report must pass and match the runtime adapter")
    if not re.fullmatch(r"[a-f0-9]{64}", adapter_sha256):
        raise TrainingRunError("runtime adapter checksum must be lowercase SHA-256")
    dataset = load_training_dataset(
        manifest_path,
        **({"config_path": config_path} if config_path is not None else {}),
    )
    if (framework.get("dataset_id"), framework.get("dataset_version")) != (
        dataset.manifest.dataset_id,
        dataset.manifest.dataset_version,
    ):
        raise TrainingRunError("training-framework report dataset identity does not match")
    examples_by_id = {example.example_id: example for example in dataset.examples}
    framework_cases = framework.get("cases")
    if not isinstance(framework_cases, list) or not framework_cases:
        raise TrainingRunError("training-framework report has no cases")

    cases: list[dict[str, Any]] = []
    started = time.perf_counter()
    for framework_case in framework_cases:
        if not isinstance(framework_case, dict):
            raise TrainingRunError("training-framework report contains an invalid case")
        example_id = framework_case.get("example_id")
        if not isinstance(example_id, str):
            raise TrainingRunError("training-framework case has no example identity")
        example = examples_by_id.get(example_id)
        if example is None:
            raise TrainingRunError(f"training-framework case is absent from dataset: {example_id}")
        answer = _runtime_chat_completion(
            runtime_base_url,
            model=runtime_model,
            messages=example.messages[:-1],
            max_new_tokens=max_new_tokens,
            seed=config["training"]["seed"],
        )
        scores = score_behavior(
            task=example.task,
            language=example.language,
            answer=answer,
            expected=example.messages[-1]["content"],
            expected_citations=example.expected_citations,
            target_json_schema=example.target_json_schema,
            user_prompt=example.messages[-2]["content"],
            system_prompt=example.messages[0]["content"],
        )
        framework_answer = framework_case.get("answer")
        if not isinstance(framework_answer, str):
            raise TrainingRunError("training-framework case has no answer text")
        cases.append(
            {
                "example_id": example.example_id,
                "task": example.task,
                "language": example.language,
                "answer": answer,
                "framework_runtime_token_f1": round(token_f1(answer, framework_answer), 6),
                "exact_framework_match": answer == framework_answer,
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
    parity_f1 = sum(case["framework_runtime_token_f1"] for case in cases) / len(cases)
    exact_match_rate = sum(case["exact_framework_match"] for case in cases) / len(cases)
    framework_validity = float(framework["metrics"]["task_validity"])
    failures: list[str] = []
    if mean_f1 < 0.5:
        failures.append(f"mean_token_f1 {mean_f1:.3f} < 0.500")
    if language_rate < 0.9:
        failures.append(f"language_adherence {language_rate:.3f} < 0.900")
    if validity_rate < 0.8:
        failures.append(f"task_validity {validity_rate:.3f} < 0.800")
    if parity_f1 < 0.8:
        failures.append(f"framework_runtime_token_f1 {parity_f1:.3f} < 0.800")
    if validity_rate < framework_validity - 0.05:
        failures.append(
            f"task_validity runtime drift {validity_rate - framework_validity:.3f} < -0.050"
        )
    report = {
        "schema_version": "1.0",
        "report_type": "deployed_gguf_adapter_behavior",
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": not failures,
        "adapter_id": adapter_id,
        "adapter_sha256": adapter_sha256,
        "runtime_model": runtime_model,
        "dataset_id": dataset.manifest.dataset_id,
        "dataset_version": dataset.manifest.dataset_version,
        "case_count": len(cases),
        "metrics": {
            "mean_token_f1": round(mean_f1, 6),
            "language_adherence": round(language_rate, 6),
            "task_validity": round(validity_rate, 6),
            "behavior_score": round((mean_f1 + language_rate + validity_rate) / 3, 6),
            "framework_runtime_token_f1": round(parity_f1, 6),
            "exact_framework_match_rate": round(exact_match_rate, 6),
            "task_validity_delta": round(validity_rate - framework_validity, 6),
        },
        "slices": summary,
        "threshold_failures": failures,
        "wall_clock_seconds": round(time.perf_counter() - started, 3),
        "cases": cases,
    }
    write_json_report(report, output)
    return report


def run_candidate_evaluation(
    config: Mapping[str, Any],
    *,
    manifest_path: Path,
    training_manifest_path: Path | None = None,
    adapter_path: Path,
    training_report_path: Path,
    output: Path,
    local_files_only: bool = True,
    max_new_tokens: int = 192,
    config_path: Path | None = None,
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
    dataset = load_training_dataset(
        manifest_path, **({"config_path": config_path} if config_path is not None else {})
    )

    def count_tokens(messages: Sequence[Mapping[str, str]]) -> int:
        return len(_input_ids(tokenizer.apply_chat_template(list(messages), tokenize=True, add_generation_prompt=False)))

    analysis = analyze_training_dataset(dataset, token_counter=count_tokens)
    source_manifest_path = training_manifest_path or manifest_path
    if source_manifest_path == manifest_path:
        training_dataset = dataset
        training_analysis = analysis
    else:
        training_dataset = load_training_dataset(
            source_manifest_path,
            **({"config_path": config_path} if config_path is not None else {}),
        )
        training_analysis = analyze_training_dataset(
            training_dataset,
            token_counter=count_tokens,
        )
        if training_analysis.dataset_checksum == analysis.dataset_checksum:
            raise TrainingRunError("independent development dataset duplicates training dataset")
        if any(split != "held_out" for split in analysis.assignments.values()):
            raise TrainingRunError(
                "independent development manifest must assign every example to held_out"
            )
    if training_report.get("dataset_checksum") != training_analysis.dataset_checksum:
        raise TrainingRunError("training report dataset checksum does not match training dataset")
    if (
        training_report.get("dataset_id"),
        training_report.get("dataset_version"),
    ) != (
        training_dataset.manifest.dataset_id,
        training_dataset.manifest.dataset_version,
    ):
        raise TrainingRunError("training report dataset identity does not match training dataset")
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
                eos_token_id=[
                    tokenizer.eos_token_id,
                    config["prompt_contract"]["control_token_ids"]["<end_of_turn>"],
                ],
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
            system_prompt=example.messages[0]["content"],
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
        "training_dataset_id": training_dataset.manifest.dataset_id,
        "training_dataset_version": training_dataset.manifest.dataset_version,
        "training_dataset_checksum": training_analysis.dataset_checksum,
        "independent_development_dataset": source_manifest_path != manifest_path,
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
        "held_out_selection_eligible": selected["held_out_passed"],
        "promotion_eligible": False,
        "promotion_note": (
            "development held-out evidence cannot authorize promotion; protected runtime and "
            "regression gates remain required"
        ),
        "candidates": sorted(candidates, key=lambda item: item["adapter_id"]),
    }
    write_json_report(report, output)
    return report
