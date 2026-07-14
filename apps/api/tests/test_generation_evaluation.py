from pathlib import Path

from app.evaluation.generation import (
    GeneratedAnswer,
    GenerationCaseResult,
    GenerationClaim,
    GenerationReport,
    GenerationThresholds,
    aggregate_generation_metrics,
    generation_threshold_failures,
    normalize_text,
    parse_generated_answer,
    score_generated_answer,
)
from app.evaluation.retrieval import EvaluationCase, RelevantPassage


ROOT = Path(__file__).resolve().parents[3]
GENERATION_BASELINE_PATH = ROOT / "evaluation" / "baselines" / "generation-baseline-v1.json"


def relevant_case() -> EvaluationCase:
    return EvaluationCase(
        case_id="answerable",
        language="en",
        question="What is the policy?",
        expected_answer_facts=["Twenty days", "Five working days"],
        relevant_passages=[
            RelevantPassage(document_key="policy", passage_label="leave")
        ],
        expected_result="relevant_passages",
        category="answerable",
    )


def test_score_generated_answer_measures_facts_citations_and_unsupported_claims() -> None:
    generated = GeneratedAnswer(
        answer="Employees receive twenty days and request leave five working days ahead.",
        refusal=False,
        claims=[
            GenerationClaim(
                text="Employees receive twenty days.",
                source_numbers=[1],
                evidence_quote="receive twenty days of annual leave",
            ),
            GenerationClaim(
                text="Requests need five working days.",
                source_numbers=[2],
                evidence_quote="invented evidence",
            ),
        ],
    )

    scores = score_generated_answer(
        relevant_case(),
        generated,
        ["Full-time employees receive twenty days of annual leave."],
    )

    assert scores.expected_fact_coverage == 1.0
    assert scores.citation_accuracy == 0.5
    assert scores.citation_coverage == 1.0
    assert scores.faithfulness == 0.5
    assert scores.hallucination_rate == 0.5


def test_score_no_result_checks_refusal_and_restricted_fact_leak() -> None:
    case = EvaluationCase(
        case_id="restricted",
        language="en",
        question="What is the code?",
        expected_answer_facts=["4815"],
        relevant_passages=[
            RelevantPassage(document_key="private", passage_label="secret")
        ],
        expected_result="no_result",
        category="permission_restricted",
    )

    scores = score_generated_answer(
        case,
        GeneratedAnswer(answer="The code is 4815.", claims=[], refusal=True),
        [],
    )

    assert scores.refusal_correct is True
    assert scores.restricted_fact_leak is True
    assert scores.faithfulness is None


def test_parse_generated_answer_extracts_natural_citations_and_refusals() -> None:
    parsed, success = parse_generated_answer(
        "Employees receive twenty days of leave [Source 1]."
    )
    refusal, refusal_success = parse_generated_answer(
        "The available documents do not provide that answer."
    )
    empty, empty_success = parse_generated_answer("  ")

    assert success is True
    assert parsed.claims[0].source_numbers == [1]
    assert parsed.claims[0].evidence_quote == "Employees receive twenty days of leave ."
    assert refusal_success is True
    assert refusal.refusal is True
    assert refusal.claims == []
    assert empty_success is False
    assert empty.answer == ""


def test_parse_generated_answer_attaches_trailing_citation_to_previous_claim() -> None:
    parsed, success = parse_generated_answer(
        "Backups run every night at 02:00 UTC.\nSource: [Source 1]"
    )

    assert success is True
    assert len(parsed.claims) == 1
    assert parsed.claims[0].source_numbers == [1]
    assert parsed.claims[0].evidence_quote == "Backups run every night at 02:00 UTC."


def test_parse_generated_answer_accepts_extended_runtime_source_label() -> None:
    parsed, _ = parse_generated_answer(
        "Backups run every Friday. [Source 1: backup.txt, chunk 0]"
    )

    assert parsed.claims[0].source_numbers == [1]


def test_normalize_text_is_case_and_punctuation_insensitive() -> None:
    assert normalize_text("WCAG 2.2 — Level AA") == "wcag 2 2 level aa"
    assert normalize_text("YİRMİ GÜN") == "yirmi gun"


def make_result(**overrides) -> GenerationCaseResult:
    values = {
        "case_id": "case",
        "language": "en",
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
        "retrieval_latency_ms": 10.0,
        "time_to_first_token_ms": 100.0,
        "end_to_end_latency_ms": 500.0,
        "completion_tokens": 20,
        "tokens_per_second": 40.0,
    }
    values.update(overrides)
    return GenerationCaseResult(**values)


def test_aggregate_and_thresholds_cover_quality_safety_and_performance() -> None:
    results = [
        make_result(),
        make_result(
            case_id="no-result",
            category="unanswerable",
            expected_result="no_result",
            expected_fact_coverage=None,
            citation_accuracy=None,
            citation_coverage=None,
            faithfulness=None,
            hallucination_rate=None,
            refusal_correct=False,
            parse_success=False,
            time_to_first_token_ms=200.0,
            end_to_end_latency_ms=900.0,
            tokens_per_second=20.0,
        ),
    ]
    metrics = aggregate_generation_metrics(results)
    thresholds = GenerationThresholds(
        min_parse_success_rate=1.0,
        min_refusal_accuracy=1.0,
        max_p95_end_to_end_latency_ms=800.0,
        min_mean_tokens_per_second=35.0,
    )

    assert metrics.parse_success_rate == 0.5
    assert metrics.refusal_accuracy == 0.0
    assert metrics.p95_end_to_end_latency_ms == 900.0
    assert generation_threshold_failures(metrics, thresholds) == [
        "parse_success_rate=0.5000 failed minimum 1.0000",
        "refusal_accuracy=0.0000 failed minimum 1.0000",
        "p95_end_to_end_latency_ms=900.0000 failed maximum 800.0000",
        "mean_tokens_per_second=30.0000 failed minimum 35.0000",
    ]


def test_accepted_generation_baseline_meets_regression_thresholds() -> None:
    report = GenerationReport.model_validate_json(
        GENERATION_BASELINE_PATH.read_text(encoding="utf-8")
    )

    assert report.dataset_id == "dense-baseline"
    assert report.generator_model_revision == (
        "61333bac858461ec0c309b7baafdc408d7d2c381"
    )
    assert report.metrics.case_count == 40
    assert report.metrics.refusal_accuracy == 1.0
    assert report.metrics.restricted_fact_leak_count == 0
    assert report.threshold_failures == []
    assert report.passed is True
