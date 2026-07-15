from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from training.foundation import TrainingFoundationError, get_hugging_face_token, write_json_report


REFUSAL_PATTERNS = (
    "do not provide",
    "does not provide",
    "does not contain the answer",
    "not provided",
    "cannot answer",
    "unable to answer",
    "no accessible document",
    "belirtilmem",
    "bulunmam",
    "bilgi yok",
    "cevaplanamaz",
)


def load_diagnostics(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingFoundationError(f"Could not load continuity diagnostics {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise TrainingFoundationError("Continuity diagnostics schema_version must be 1")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise TrainingFoundationError("Continuity diagnostics must contain at least one case")
    required = {
        "case_id",
        "language",
        "system",
        "user",
        "required_term_groups",
        "forbidden_terms",
        "expect_refusal",
        "expect_citation",
    }
    for case in cases:
        if not isinstance(case, dict) or required - case.keys():
            raise TrainingFoundationError("Every continuity case must define the full contract")
    return payload


def render_messages(case: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": case["system"]},
        {"role": "user", "content": case["user"]},
    ]


def validate_tokenizer_contract(config: dict[str, Any], tokenizer: Any) -> dict[str, Any]:
    prompt_contract = config["prompt_contract"]
    expected_vocab_size = int(prompt_contract["tokenizer_vocab_size"])
    if tokenizer.vocab_size != expected_vocab_size:
        raise TrainingFoundationError(
            "Pinned tokenizer is incomplete or mismatched: "
            f"expected vocab_size {expected_vocab_size}; found {tokenizer.vocab_size}"
        )
    actual_control_ids = {
        token: tokenizer.convert_tokens_to_ids(token)
        for token in prompt_contract["control_token_ids"]
    }
    if actual_control_ids != prompt_contract["control_token_ids"]:
        raise TrainingFoundationError(
            "Pinned tokenizer control-token IDs do not match the prompt contract"
        )
    return {
        "vocab_size": tokenizer.vocab_size,
        "control_token_ids": actual_control_ids,
    }


def score_answer(case: dict[str, Any], answer: str) -> dict[str, Any]:
    folded = answer.casefold()
    missing_groups = [
        group
        for group in case["required_term_groups"]
        if not any(str(term).casefold() in folded for term in group)
    ]
    forbidden_matches = [term for term in case["forbidden_terms"] if term.casefold() in folded]
    refusal = any(pattern in folded for pattern in REFUSAL_PATTERNS)
    refusal_matches = refusal == case["expect_refusal"]
    citation_present = bool(re.search(r"\[source\s+\d+[^\]]*\]", answer, re.IGNORECASE))
    content_passed = not missing_groups and not forbidden_matches and refusal_matches
    return {
        "passed": content_passed and citation_present == case["expect_citation"],
        "content_passed": content_passed,
        "missing_term_groups": missing_groups,
        "forbidden_matches": forbidden_matches,
        "refusal": refusal,
        "refusal_matches": refusal_matches,
        "citation_present": citation_present,
        "citation_matches": citation_present == case["expect_citation"],
    }


def verify_chat_template(
    config: dict[str, Any],
    *,
    template_path: Path,
    output: Path,
    local_files_only: bool,
) -> dict[str, Any]:
    try:
        from transformers import AutoTokenizer  # type: ignore[import-not-found]
    except (ImportError, OSError) as exc:
        raise TrainingFoundationError("Template verification requires offline-ai-training") from exc

    base_model = config["base_model"]
    template = template_path.read_text(encoding="utf-8")
    template_sha256 = hashlib.sha256(template.encode()).hexdigest()
    if template_sha256 != config["prompt_contract"]["chat_template_sha256"]:
        raise TrainingFoundationError("Chat template SHA-256 does not match the pinned contract")
    tokenizer = AutoTokenizer.from_pretrained(
        base_model["repo_id"],
        revision=base_model["revision"],
        token=get_hugging_face_token(),
        local_files_only=local_files_only,
    )
    tokenizer_metadata = validate_tokenizer_contract(config, tokenizer)
    upstream_template_present = bool(tokenizer.chat_template)
    tokenizer.chat_template = template
    messages = [
        {"role": "system", "content": "SYSTEM CONTRACT"},
        {"role": "user", "content": "USER QUESTION"},
    ]
    rendered = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    expected_fragments = (
        "<bos><start_of_turn>user\nSYSTEM CONTRACT\n\nUSER QUESTION<end_of_turn>\n",
        "<start_of_turn>model\n",
    )
    passed = all(fragment in rendered for fragment in expected_fragments)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "experiment_id": config["experiment_id"],
        "base_model": base_model,
        "upstream_template_present": upstream_template_present,
        "template_path": str(template_path),
        "template_sha256": template_sha256,
        "rendered_prompt_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
        "special_tokens": {
            "bos": [tokenizer.bos_token, tokenizer.bos_token_id],
            "eos": [tokenizer.eos_token, tokenizer.eos_token_id],
            "pad": [tokenizer.pad_token, tokenizer.pad_token_id],
        },
        "tokenizer": tokenizer_metadata,
        "system_role_strategy": "prepend_to_first_user_turn",
        "passed": passed,
    }
    write_json_report(report, output)
    return report


def generate_source_answers(
    config: dict[str, Any],
    diagnostics: dict[str, Any],
    *,
    template_path: Path,
    local_files_only: bool,
) -> dict[str, str]:
    try:
        import torch  # type: ignore[import-not-found]
        from transformers import (  # type: ignore[import-not-found]
            AutoModelForCausalLM,
            AutoTokenizer,
        )
    except (ImportError, OSError) as exc:
        raise TrainingFoundationError("Source diagnostics require offline-ai-training") from exc
    if not torch.cuda.is_available():
        raise TrainingFoundationError("Source diagnostics require a CUDA device")

    seed = int(diagnostics["seed"])
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    base_model = config["base_model"]
    token = get_hugging_face_token()
    tokenizer = AutoTokenizer.from_pretrained(
        base_model["repo_id"],
        revision=base_model["revision"],
        token=token,
        local_files_only=local_files_only,
    )
    validate_tokenizer_contract(config, tokenizer)
    tokenizer.chat_template = template_path.read_text(encoding="utf-8")
    model = AutoModelForCausalLM.from_pretrained(
        base_model["repo_id"],
        revision=base_model["revision"],
        token=token,
        local_files_only=local_files_only,
        dtype=torch.bfloat16,
    ).to("cuda")
    model.eval()
    answers: dict[str, str] = {}
    for case in diagnostics["cases"]:
        encoded = tokenizer.apply_chat_template(
            render_messages(case),
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        ).to("cuda")
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                do_sample=False,
                max_new_tokens=int(diagnostics["max_new_tokens"]),
            )
        completion = generated[0, encoded["input_ids"].shape[1] :]
        answers[case["case_id"]] = tokenizer.decode(completion, skip_special_tokens=True).strip()
    return answers


def generate_runtime_answers(
    diagnostics: dict[str, Any],
    *,
    runtime_url: str,
    request_json: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, str]:
    sender = request_json or _request_json
    answers: dict[str, str] = {}
    for case in diagnostics["cases"]:
        response = sender(
            f"{runtime_url.rstrip('/')}/chat/completions",
            {
                "messages": render_messages(case),
                "temperature": 0,
                "seed": diagnostics["seed"],
                "max_tokens": diagnostics["max_new_tokens"],
                "stream": False,
            },
        )
        try:
            answers[case["case_id"]] = response["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise TrainingFoundationError("Runtime returned an invalid chat completion") from exc
    return answers


def _request_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:  # noqa: S310 - explicit localhost CLI target
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TrainingFoundationError(f"Could not query runtime at {url}: {exc}") from exc
    if not isinstance(result, dict):
        raise TrainingFoundationError("Runtime response must be a JSON object")
    return result


def build_continuity_report(
    config: dict[str, Any],
    diagnostics: dict[str, Any],
    *,
    source_answers: dict[str, str],
    runtime_answers: dict[str, str],
    runtime_url: str,
) -> dict[str, Any]:
    cases = []
    for case in diagnostics["cases"]:
        case_id = case["case_id"]
        source_score = score_answer(case, source_answers[case_id])
        runtime_score = score_answer(case, runtime_answers[case_id])
        cases.append(
            {
                "case_id": case_id,
                "language": case["language"],
                "source": {"answer": source_answers[case_id], **source_score},
                "runtime": {"answer": runtime_answers[case_id], **runtime_score},
                "behavior_equivalent": (
                    source_score["content_passed"] and runtime_score["content_passed"]
                ),
            }
        )
    citation_cases = [
        case for case, result in zip(diagnostics["cases"], cases, strict=True)
        if case["expect_citation"] and result["source"]["content_passed"]
    ]
    if not citation_cases:
        raise TrainingFoundationError("Continuity diagnostics must include citation cases")
    citation_case_ids = {case["case_id"] for case in citation_cases}
    source_citation_rate = sum(
        case["source"]["citation_present"]
        for case in cases
        if case["case_id"] in citation_case_ids
    ) / len(citation_cases)
    runtime_citation_rate = sum(
        case["runtime"]["citation_present"]
        for case in cases
        if case["case_id"] in citation_case_ids
    ) / len(citation_cases)
    citation_rate_drift = source_citation_rate - runtime_citation_rate
    thresholds = {
        "minimum_runtime_citation_rate": 0.75,
        "maximum_source_to_runtime_citation_rate_drift": 0.25,
    }
    citation_gate_passed = (
        runtime_citation_rate >= thresholds["minimum_runtime_citation_rate"]
        and citation_rate_drift
        <= thresholds["maximum_source_to_runtime_citation_rate_drift"]
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "diagnostic_id": diagnostics["diagnostic_id"],
        "source_model": config["base_model"],
        "runtime_url": runtime_url,
        "seed": diagnostics["seed"],
        "cases": cases,
        "citation_metrics": {
            "source_rate": source_citation_rate,
            "runtime_rate": runtime_citation_rate,
            "source_to_runtime_drift": citation_rate_drift,
        },
        "thresholds": thresholds,
        "citation_gate_passed": citation_gate_passed,
        "passed": all(case["behavior_equivalent"] for case in cases) and citation_gate_passed,
    }


def format_continuity_summary(report: dict[str, Any]) -> str:
    lines = [f"Training continuity: {'PASS' if report['passed'] else 'FAIL'}"]
    for case in report["cases"]:
        lines.append(
            f"[{('PASS' if case['behavior_equivalent'] else 'FAIL')}] {case['case_id']}: "
            f"source-content={'pass' if case['source']['content_passed'] else 'fail'}, "
            f"runtime-content={'pass' if case['runtime']['content_passed'] else 'fail'}, "
            f"source-citation={'yes' if case['source']['citation_present'] else 'no'}, "
            f"runtime-citation={'yes' if case['runtime']['citation_present'] else 'no'}"
        )
    lines.append(
        "Citation rate: "
        f"source={report['citation_metrics']['source_rate']:.3f}, "
        f"runtime={report['citation_metrics']['runtime_rate']:.3f}, "
        f"drift={report['citation_metrics']['source_to_runtime_drift']:.3f}"
    )
    return "\n".join(lines)
