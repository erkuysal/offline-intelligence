from __future__ import annotations

from pathlib import Path

import pytest

from training.continuity import (
    build_continuity_report,
    generate_runtime_answers,
    load_diagnostics,
    render_messages,
    score_answer,
    validate_tokenizer_contract,
)
from training.foundation import load_training_config


ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "training" / "gemma3-1b-lora-v1.json"
DIAGNOSTICS_PATH = ROOT / "config" / "training" / "continuity-diagnostics-v1.json"


def test_diagnostics_cover_grounding_languages_refusal_and_instruction_isolation() -> None:
    diagnostics = load_diagnostics(DIAGNOSTICS_PATH)

    assert {case["language"] for case in diagnostics["cases"]} == {"en", "tr"}
    assert any(case["expect_refusal"] for case in diagnostics["cases"])
    assert any("instruction-isolation" in case["case_id"] for case in diagnostics["cases"])


def test_render_messages_preserves_production_system_and_user_roles() -> None:
    case = load_diagnostics(DIAGNOSTICS_PATH)["cases"][0]

    assert render_messages(case) == [
        {"role": "system", "content": case["system"]},
        {"role": "user", "content": case["user"]},
    ]


def test_score_answer_enforces_terms_refusal_and_forbidden_content() -> None:
    diagnostics = load_diagnostics(DIAGNOSTICS_PATH)
    answerable = diagnostics["cases"][0]
    refusal = diagnostics["cases"][2]

    assert score_answer(
        answerable,
        "Backups run at 02:00 UTC and drills happen Friday. [Source 1]",
    )["passed"]
    assert not score_answer(answerable, "Backups run nightly.")["passed"]
    assert score_answer(refusal, "The available documents do not provide the answer.")["passed"]
    assert not score_answer(refusal, "The code is 4815.")["passed"]


def test_runtime_generation_uses_openai_chat_contract() -> None:
    diagnostics = {**load_diagnostics(DIAGNOSTICS_PATH), "cases": [load_diagnostics(DIAGNOSTICS_PATH)["cases"][0]]}
    calls: list[tuple[str, dict]] = []

    def fake_request(url: str, payload: dict) -> dict:
        calls.append((url, payload))
        return {"choices": [{"message": {"content": "answer"}}]}

    answers = generate_runtime_answers(
        diagnostics,
        runtime_url="http://localhost:18080/v1/",
        request_json=fake_request,
    )

    assert answers == {"en-grounded-citation": "answer"}
    assert calls[0][0] == "http://localhost:18080/v1/chat/completions"
    assert calls[0][1]["temperature"] == 0
    assert calls[0][1]["messages"][0]["role"] == "system"


def test_continuity_requires_both_source_and_runtime_to_pass() -> None:
    config = load_training_config(CONFIG_PATH)
    diagnostics = {**load_diagnostics(DIAGNOSTICS_PATH), "cases": [load_diagnostics(DIAGNOSTICS_PATH)["cases"][0]]}
    source = {"en-grounded-citation": "02:00 UTC and Friday. [Source 1]"}
    runtime = {"en-grounded-citation": "02:00 UTC and Friday without citation"}

    report = build_continuity_report(
        config,
        diagnostics,
        source_answers=source,
        runtime_answers=runtime,
        runtime_url="http://localhost:18080/v1",
    )

    assert report["passed"] is False
    assert report["cases"][0]["source"]["passed"] is True
    assert report["cases"][0]["runtime"]["passed"] is False


def test_tokenizer_contract_rejects_incomplete_placeholder_tokenizer() -> None:
    config = load_training_config(CONFIG_PATH)

    class PlaceholderTokenizer:
        vocab_size = 5

        @staticmethod
        def convert_tokens_to_ids(_token: str) -> int:
            return 3

    with pytest.raises(ValueError, match="expected vocab_size 262144; found 5"):
        validate_tokenizer_contract(config, PlaceholderTokenizer())
