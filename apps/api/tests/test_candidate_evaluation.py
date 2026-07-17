from __future__ import annotations

import json
from pathlib import Path

import pytest

from training.candidate_evaluation import (
    build_candidate_selection_report,
    score_behavior,
    token_f1,
)


ROOT = Path(__file__).resolve().parents[3]


def test_token_f1_rewards_matching_behavior_target() -> None:
    assert token_f1("The queue runs at 05:20 UTC.", "The queue runs at 05:20 UTC.") == 1.0
    assert token_f1("unrelated", "The queue runs at 05:20 UTC.") == 0.0


def test_grounded_answer_requires_declared_citation() -> None:
    common = {
        "task": "grounded_answer",
        "language": "en",
        "expected": "The queue runs at 05:20 UTC. [source-one#facts]",
        "expected_citations": ({"source_id": "source-one", "passage_id": "facts"},),
        "target_json_schema": None,
        "user_prompt": "When does the queue run?",
    }
    assert score_behavior(answer=common["expected"], **common)["task_valid"] is True
    assert score_behavior(answer="The queue runs at 05:20 UTC.", **common)["task_valid"] is False


def test_grounded_answer_accepts_declared_runtime_citation() -> None:
    result = score_behavior(
        task="grounded_answer",
        language="en",
        answer="The queue runs at 05:20 UTC. [Source 1]",
        expected="The queue runs at 05:20 UTC. [Source 1]",
        expected_citations=(
            {
                "source_id": "source-one",
                "passage_id": "facts",
                "runtime_label": "[Source 1]",
            },
        ),
        target_json_schema=None,
        user_prompt="When does the queue run?",
    )

    assert result["task_valid"] is True


def test_refusal_json_and_incident_contracts_are_task_specific() -> None:
    refusal = score_behavior(
        task="grounded_refusal",
        language="tr",
        answer="Bu soruyu yanıtlamak için kaynakta yeterli bilgi bulunmuyor.",
        expected="Kaynakta yeterli bilgi bulunmuyor.",
        expected_citations=(),
        target_json_schema=None,
        user_prompt="İrtibat kimdir?",
    )
    structured = score_behavior(
        task="json_output",
        language="en",
        answer='{"service":"Atlas","status":"operational"}',
        expected='{"service":"Atlas","status":"operational"}',
        expected_citations=(),
        target_json_schema={"required": ["service", "status"]},
        user_prompt="Return JSON.",
    )
    incident = score_behavior(
        task="incident_report",
        language="en",
        answer="Impact: Delay.\nTimeline: 05:00.\nCause: Dependency.\nAction: Monitor.",
        expected="",
        expected_citations=(),
        target_json_schema=None,
        user_prompt="Write a report.",
    )
    assert refusal["task_valid"] is True
    assert structured["task_valid"] is True
    assert incident["task_valid"] is True


def test_v3_production_refusal_incident_and_terminology_contracts() -> None:
    refusal = score_behavior(
        task="grounded_refusal",
        language="en",
        answer="The available documents do not provide the answer.",
        expected="The available documents do not provide the answer.",
        expected_citations=(),
        target_json_schema=None,
        user_prompt="Do not guess.",
    )
    incident = score_behavior(
        task="incident_report",
        language="tr",
        answer="Etki: Kesinti.\nZaman Çizelgesi: 05:00.\nNeden: Test.\nEylem: Geri alındı.",
        expected="",
        expected_citations=(),
        target_json_schema=None,
        user_prompt="Olayı özetleyin.",
    )
    terminology = score_behavior(
        task="terminology",
        language="en",
        answer="The saved restart position is the recovery coordinate. [Source 1]",
        expected="The saved restart position is the recovery coordinate. [Source 1]",
        expected_citations=(),
        target_json_schema=None,
        user_prompt="Use only the approved term.",
        system_prompt=(
            "The approved term is recovery coordinate; obsolete pointer is deprecated."
        ),
    )

    assert refusal["task_valid"] is True
    assert incident["task_valid"] is True
    assert terminology["task_valid"] is True


@pytest.mark.parametrize(
    "dataset",
    (
        "phase5-behavior-training-v3",
        "phase5-behavior-development-v3",
    ),
)
def test_v3_reference_targets_pass_candidate_scorer(dataset: str) -> None:
    examples_path = ROOT / "training" / "datasets" / dataset / "examples.jsonl"

    for line in examples_path.read_text(encoding="utf-8").splitlines():
        example = json.loads(line)
        messages = example["messages"]
        scores = score_behavior(
            task=example["task"],
            language=example["language"],
            answer=messages[-1]["content"],
            expected=messages[-1]["content"],
            expected_citations=example["expected_citations"],
            target_json_schema=example.get("target_json_schema"),
            user_prompt=messages[-2]["content"],
            system_prompt=messages[0]["content"],
        )
        assert scores["language_adherent"] is True, example["example_id"]
        assert scores["task_valid"] is True, example["example_id"]


def test_terminology_uses_distinct_last_quoted_phrase_as_forbidden() -> None:
    result = score_behavior(
        task="terminology",
        language="tr",
        answer="Yedekleme döngüsü saat 16:40 UTC'de başlar.",
        expected="Yedekleme döngüsü saat 16:40 UTC'de başlar.",
        expected_citations=(),
        target_json_schema=None,
        user_prompt=(
            "Standart terim 'yedekleme döngüsü'. Tam olarak 'yedekleme döngüsü' terimini "
            "kullan ve 'eski periyot' ifadesini kullanma."
        ),
    )
    assert result["task_valid"] is True


def test_turkish_terminology_ignores_apostrophe_in_source_sentence() -> None:
    result = score_behavior(
        task="terminology",
        language="tr",
        answer="Yönlendirme aralığı saat 19:25 UTC'de başlar.",
        expected="Yönlendirme aralığı saat 19:25 UTC'de başlar.",
        expected_citations=(),
        target_json_schema=None,
        user_prompt=(
            "Hizmet saat 19:25 UTC'de çalışır. Standart terim 'yönlendirme aralığı'.\n\n"
            "Tam standart terim 'yönlendirme aralığı' ifadesini kullan. 'Eski periyot' deme."
        ),
    )
    assert result["task_valid"] is True


def test_language_detection_understands_language_specific_json_fields() -> None:
    result = score_behavior(
        task="json_output",
        language="tr",
        answer='{"hizmet":"Ardıç","durum":"çalışıyor"}',
        expected='{"hizmet":"Ardıç","durum":"çalışıyor"}',
        expected_citations=(),
        target_json_schema={
            "required": ["hizmet", "durum"],
            "properties": {"durum": {"enum": ["çalışıyor"]}},
        },
        user_prompt="JSON döndür.",
    )
    assert result["language_adherent"] is True
    assert result["task_valid"] is True


def test_development_selection_never_claims_production_promotion(tmp_path: Path) -> None:
    training_path = tmp_path / "training.json"
    held_out_path = tmp_path / "held-out.json"
    output = tmp_path / "selection.json"
    training_path.write_text(
        json.dumps(
            {
                "passed": True,
                "adapter_id": "adapter-v2",
                "run_fingerprint": "a" * 64,
                "run_manifest": {
                    "lora": {"rank": 16},
                    "optimizer": {"learning_rate": 0.0002},
                },
                "validation_loss": [{"step": 159, "loss": 0.01}],
            }
        ),
        encoding="utf-8",
    )
    held_out_path.write_text(
        json.dumps(
            {
                "passed": True,
                "adapter_id": "adapter-v2",
                "dataset_id": "development-v2",
                "dataset_version": "2.0.1",
                "dataset_checksum": "b" * 64,
                "threshold_failures": [],
                "metrics": {"behavior_score": 1.0},
            }
        ),
        encoding="utf-8",
    )

    report = build_candidate_selection_report(
        [training_path], [held_out_path], output=output
    )

    assert report["held_out_selection_eligible"] is True
    assert report["promotion_eligible"] is False
    assert "protected runtime" in report["promotion_note"]
