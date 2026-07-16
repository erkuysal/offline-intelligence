from __future__ import annotations

from training.candidate_evaluation import score_behavior, token_f1


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
        answer="Summary: Late.\nImpact: Delay.\nCause: Dependency.\nAction: Monitor.",
        expected="",
        expected_citations=(),
        target_json_schema=None,
        user_prompt="Write a report.",
    )
    assert refusal["task_valid"] is True
    assert structured["task_valid"] is True
    assert incident["task_valid"] is True


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
