from pathlib import Path

import pytest

from app.evaluation.adaptation import (
    PromotionThresholds,
    TaskThresholds,
    aggregate_task_metrics,
    build_adaptation_evaluation_report,
    promotion_threshold_failures,
    task_threshold_failures,
)
from app.evaluation.generation import (
    GenerationCaseResult,
    GenerationReport,
    GenerationThresholds,
    aggregate_generation_metrics,
)


ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = ROOT / "evaluation" / "baselines" / "generation-baseline-v1.json"


def make_case(task: str, language: str = "en", **overrides) -> GenerationCaseResult:
    values = {
        "case_id": f"{language}-{task}",
        "language": language,
        "category": "answerable",
        "expected_result": "relevant_passages",
        "answer": "answer",
        "refusal": False,
        "parse_success": True,
        "source_count": 1,
        "expected_fact_coverage": 1.0,
        "citation_accuracy": 1.0,
        "citation_coverage": 1.0,
        "faithfulness": 1.0,
        "hallucination_rate": 0.0,
        "refusal_correct": None,
        "restricted_fact_leak": False,
        "retrieval_latency_ms": 1.0,
        "time_to_first_token_ms": 10.0,
        "end_to_end_latency_ms": 20.0,
        "completion_tokens": 10,
        "tokens_per_second": 30.0,
        "task": task,
        "language_adherent": True,
    }
    values.update(overrides)
    return GenerationCaseResult(**values)


def behavior_cases() -> list[GenerationCaseResult]:
    return [
        make_case("grounded_answer", citation_format_valid=True),
        make_case(
            "grounded_refusal",
            language="tr",
            category="unanswerable",
            expected_result="no_result",
            expected_fact_coverage=None,
            citation_accuracy=None,
            citation_coverage=None,
            faithfulness=None,
            hallucination_rate=None,
            refusal_correct=True,
            supported_refusal=True,
        ),
        make_case("citation_formatting", citation_format_valid=True),
        make_case("json_output", json_schema_valid=True),
        make_case("incident_report", incident_report_structure_valid=True),
        make_case("terminology", terminology_consistent=True),
    ]


def make_report(
    cases: list[GenerationCaseResult],
    mode: str,
    *,
    dataset_id: str = "behavior-v1",
) -> GenerationReport:
    baseline = GenerationReport.model_validate_json(BASELINE_PATH.read_text(encoding="utf-8"))
    return baseline.model_copy(
        update={
            "evaluation_mode": mode,
            "adapter_id": "adapter-test-v1" if mode.startswith("adapter") else None,
            "dataset_id": dataset_id,
            "metrics": aggregate_generation_metrics(cases),
            "thresholds": GenerationThresholds(),
            "threshold_failures": [],
            "cases": cases,
        }
    )


def regression_reports(
    cases: list[GenerationCaseResult] | None = None,
) -> dict[str, GenerationReport]:
    regression_cases = cases or behavior_cases()
    return {
        "base_rag": make_report(
            regression_cases,
            "base_rag",
            dataset_id="phase-4-regression-v1",
        ),
        "adapter_rag": make_report(
            regression_cases,
            "adapter_rag",
            dataset_id="phase-4-regression-v1",
        ),
    }


def test_task_metrics_are_reported_globally_by_language_and_by_task() -> None:
    cases = behavior_cases()
    matrix = build_adaptation_evaluation_report(
        {
            "base": make_report(cases, "base"),
            "base_rag": make_report(cases, "base_rag"),
            "adapter": make_report(cases, "adapter"),
            "adapter_rag": make_report(cases, "adapter_rag"),
        },
        regression_reports=regression_reports(),
        task_thresholds=TaskThresholds(
            min_language_adherence=1.0,
            min_citation_format_validity=1.0,
            min_json_schema_validity=1.0,
            min_incident_report_structure=1.0,
            min_terminology_consistency=1.0,
            min_supported_refusal=1.0,
        ),
    )

    assert matrix.passed is True
    assert [mode.mode for mode in matrix.modes] == [
        "base",
        "base_rag",
        "adapter",
        "adapter_rag",
    ]
    assert matrix.modes[0].by_language["tr"].quality_safety_metrics.case_count == 1
    assert matrix.modes[0].by_language["tr"].quality_safety_metrics.refusal_accuracy == 1.0
    assert matrix.modes[0].by_task["json_output"].task_metrics.json_schema_validity == 1.0
    assert matrix.modes[0].by_task["json_output"].performance_metrics.case_count == 1
    assert matrix.modes[1].rag_enabled is True
    assert matrix.modes[2].adapter_enabled is True
    assert matrix.modes[2].adapter_id == "adapter-test-v1"
    assert matrix.promotion_thresholds.min_expected_fact_coverage == 0.75
    assert matrix.regression.dataset_id == "phase-4-regression-v1"


def test_configured_threshold_fails_when_metric_is_missing() -> None:
    metrics = aggregate_task_metrics([make_case("grounded_answer")])

    assert task_threshold_failures(
        metrics,
        TaskThresholds(min_json_schema_validity=1.0),
    ) == ["json_schema_validity was not measured; required minimum 1.0000"]


def test_task_thresholds_gate_candidate_mode_not_diagnostic_controls() -> None:
    passing_cases = behavior_cases()
    failing_base_cases = [
        case.model_copy(update={"language_adherent": False}) for case in passing_cases
    ]
    matrix = build_adaptation_evaluation_report(
        {
            "base": make_report(failing_base_cases, "base"),
            "base_rag": make_report(passing_cases, "base_rag"),
            "adapter": make_report(passing_cases, "adapter"),
            "adapter_rag": make_report(passing_cases, "adapter_rag"),
        },
        regression_reports=regression_reports(),
        task_thresholds=TaskThresholds(min_language_adherence=1.0),
    )

    assert matrix.gated_modes == ["adapter_rag"]
    assert matrix.modes[0].task_metrics.language_adherence == 0.0
    assert matrix.modes[0].threshold_failures == []
    assert matrix.passed is True


def test_behavior_source_thresholds_are_diagnostic_not_promotion_gates() -> None:
    cases = behavior_cases()
    failed_source = make_report(cases, "base_rag").model_copy(
        update={"threshold_failures": ["natural-claim metric does not fit structured output"]}
    )
    matrix = build_adaptation_evaluation_report(
        {
            "base": make_report(cases, "base"),
            "base_rag": failed_source,
            "adapter": make_report(cases, "adapter"),
            "adapter_rag": make_report(cases, "adapter_rag"),
        },
        regression_reports=regression_reports(),
        task_thresholds=TaskThresholds(),
    )

    assert matrix.modes[1].source_threshold_failures == [
        "natural-claim metric does not fit structured output"
    ]
    assert matrix.modes[1].threshold_failures == []
    assert matrix.passed is True


def test_promotion_gates_enforce_relative_runtime_regressions() -> None:
    base = make_report(behavior_cases(), "base_rag").metrics
    adapter = base.model_copy(
        update={
            "mean_time_to_first_token_ms": base.mean_time_to_first_token_ms * 1.21,
            "mean_tokens_per_second": base.mean_tokens_per_second * 0.79,
        }
    )

    failures = promotion_threshold_failures(base, adapter, PromotionThresholds())

    assert any("mean_time_to_first_token_ms" in failure for failure in failures)
    assert any("mean_tokens_per_second" in failure for failure in failures)


def test_matrix_rejects_missing_modes_and_mismatched_cases() -> None:
    cases = behavior_cases()
    report = make_report(cases, "base")
    with pytest.raises(ValueError, match="missing modes: adapter, adapter_rag"):
        build_adaptation_evaluation_report(
            {"base": report, "base_rag": make_report(cases, "base_rag")},
            regression_reports=regression_reports(),
            task_thresholds=TaskThresholds(),
        )

    other = make_report(cases[:-1], "adapter")
    with pytest.raises(ValueError, match="case IDs"):
        build_adaptation_evaluation_report(
            {
                "base": report,
                "base_rag": make_report(cases, "base_rag"),
                "adapter": other,
                "adapter_rag": make_report(cases, "adapter_rag"),
            },
            regression_reports=regression_reports(),
            task_thresholds=TaskThresholds(),
        )


def test_matrix_rejects_mislabeled_mode_report() -> None:
    cases = behavior_cases()
    with pytest.raises(ValueError, match="mode labels cannot be inferred"):
        build_adaptation_evaluation_report(
            {
                "base": make_report(cases, "base_rag"),
                "base_rag": make_report(cases, "base_rag"),
                "adapter": make_report(cases, "adapter"),
                "adapter_rag": make_report(cases, "adapter_rag"),
            },
            regression_reports=regression_reports(),
            task_thresholds=TaskThresholds(),
        )


def test_matrix_rejects_reusing_behavior_corpus_as_regression_corpus() -> None:
    cases = behavior_cases()
    with pytest.raises(ValueError, match="must use separate datasets"):
        build_adaptation_evaluation_report(
            {
                "base": make_report(cases, "base"),
                "base_rag": make_report(cases, "base_rag"),
                "adapter": make_report(cases, "adapter"),
                "adapter_rag": make_report(cases, "adapter_rag"),
            },
            regression_reports={
                "base_rag": make_report(cases, "base_rag"),
                "adapter_rag": make_report(cases, "adapter_rag"),
            },
            task_thresholds=TaskThresholds(),
        )
