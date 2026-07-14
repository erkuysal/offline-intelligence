from collections import Counter
import json
from pathlib import Path

import pytest

from app.evaluation.retrieval import (
    EvaluationReport,
    EvaluationThresholds,
    RetrievalCandidate,
    aggregate_metrics,
    evaluate_case,
    evaluate_dataset,
    format_summary,
    load_dataset,
)


ROOT = Path(__file__).resolve().parents[3]
DATASET_PATH = ROOT / "evaluation" / "datasets" / "dense-baseline-smoke-v1.jsonl"
FORMAL_DATASET_PATH = ROOT / "evaluation" / "datasets" / "dense-baseline-v1.jsonl"
BASELINE_REPORT_PATH = ROOT / "evaluation" / "baselines" / "dense-baseline-v1.json"
LEXICAL_BASELINE_REPORT_PATH = ROOT / "evaluation" / "baselines" / "lexical-baseline-v1.json"
HYBRID_BASELINE_REPORT_PATH = ROOT / "evaluation" / "baselines" / "hybrid-baseline-v1.json"
RERANKED_BASELINE_REPORT_PATH = ROOT / "evaluation" / "baselines" / "reranked-baseline-v1.json"


def test_load_dataset_validates_versioned_references() -> None:
    dataset = load_dataset(DATASET_PATH)

    assert dataset.manifest.schema_version == "1.0"
    assert {document.language for document in dataset.documents} == {"en", "tr"}
    assert {case.category for case in dataset.cases} >= {
        "answerable",
        "unanswerable",
        "ambiguous",
        "permission_restricted",
    }


def test_formal_dataset_has_balanced_20_document_40_case_contract() -> None:
    dataset = load_dataset(FORMAL_DATASET_PATH)

    assert len(dataset.documents) == 20
    assert len(dataset.cases) == 40
    assert Counter(document.language for document in dataset.documents) == {"en": 10, "tr": 10}
    assert Counter(case.language for case in dataset.cases) == {"en": 20, "tr": 20}
    assert Counter(case.category for case in dataset.cases) == {
        "answerable": 28,
        "ambiguous": 4,
        "unanswerable": 4,
        "permission_restricted": 4,
    }
    assert dataset.manifest.embedding_model_revision == (
        "8dd0ca2a66a8f14470acb0e2a71f801afbc5fb73"
    )
    assert dataset.manifest.embedding_dimensions == 768


def test_accepted_dense_baseline_report_meets_regression_thresholds() -> None:
    report = EvaluationReport.model_validate_json(BASELINE_REPORT_PATH.read_text(encoding="utf-8"))

    assert report.dataset_id == "dense-baseline"
    assert report.dataset_version == "1.0.0"
    assert report.embedding_model_revision == "8dd0ca2a66a8f14470acb0e2a71f801afbc5fb73"
    assert report.metrics.case_count == 40
    assert report.metrics.authorization_leak_count == 0
    assert report.metrics.mean_latency_ms <= 50
    assert report.metrics.p95_latency_ms <= 50
    assert report.threshold_failures == []
    assert report.passed is True


def test_accepted_lexical_baseline_report_meets_regression_thresholds() -> None:
    report = EvaluationReport.model_validate_json(
        LEXICAL_BASELINE_REPORT_PATH.read_text(encoding="utf-8")
    )

    assert report.retrieval_strategy == "lexical"
    assert report.metrics.case_count == 40
    assert report.metrics.recall_at_k >= 0.95
    assert report.metrics.precision_at_k >= 0.40
    assert report.metrics.authorization_leak_count == 0
    assert report.threshold_failures == []
    assert report.passed is True


def test_accepted_hybrid_baseline_report_meets_regression_thresholds() -> None:
    report = EvaluationReport.model_validate_json(
        HYBRID_BASELINE_REPORT_PATH.read_text(encoding="utf-8")
    )

    assert report.retrieval_strategy == "hybrid"
    assert report.metrics.case_count == 40
    assert report.metrics.recall_at_k == 1.0
    assert report.metrics.mean_reciprocal_rank == 1.0
    assert report.metrics.authorization_leak_count == 0
    assert report.threshold_failures == []
    assert report.passed is True


def test_reranked_baseline_records_no_quality_gain_and_high_latency() -> None:
    report = EvaluationReport.model_validate_json(
        RERANKED_BASELINE_REPORT_PATH.read_text(encoding="utf-8")
    )

    assert report.retrieval_strategy == "reranked"
    assert report.reranker_model == "bge-reranker-v2-m3"
    assert report.reranker_model_revision == "b5160aeac3c6c8fe7beaaaf04c9e0142826b58d1"
    assert report.metrics.recall_at_k == 1.0
    assert report.metrics.mean_reciprocal_rank == 1.0
    assert report.metrics.authorization_leak_count == 0
    assert report.metrics.mean_latency_ms > 200
    assert report.metrics.p95_latency_ms > 400
    assert report.threshold_failures == []


def test_load_dataset_rejects_unknown_passage(tmp_path: Path) -> None:
    lines = [line for line in DATASET_PATH.read_text(encoding="utf-8").splitlines() if line]
    case = json.loads(lines[-1])
    case["relevant_passages"][0]["passage_label"] = "missing"
    lines[-1] = json.dumps(case)
    invalid_path = tmp_path / "invalid.jsonl"
    invalid_path.write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown passage"):
        load_dataset(invalid_path)


def test_evaluate_dataset_reports_metrics_and_threshold_failures() -> None:
    dataset = load_dataset(DATASET_PATH)

    def retrieve(case, _limit):
        if case.expected_result == "no_result":
            return [], 2.0
        relevant = case.relevant_passages[0]
        return [
            RetrievalCandidate(
                rank=1,
                document_key=relevant.document_key,
                filename="document.txt",
                chunk_id=1,
                chunk_index=0,
                passage_label=relevant.passage_label,
                score=0.9,
            )
        ], 2.0

    report = evaluate_dataset(
        dataset,
        retrieve=retrieve,
        retrieval_limit=5,
        thresholds=EvaluationThresholds(
            min_recall_at_k=1.0,
            max_mean_latency_ms=1.0,
            max_p95_latency_ms=1.0,
        ),
        embedding_model="fake-bow",
        retrieval_strategy="lexical",
    )

    assert report.metrics.recall_at_k == 1.0
    assert report.metrics.no_result_accuracy == 1.0
    assert report.metrics.authorization_leak_count == 0
    assert report.retrieval_strategy == "lexical"
    assert format_summary(report).startswith("Lexical retrieval evaluation: FAILED")
    assert report.passed is False
    assert report.threshold_failures == [
        "mean_latency_ms=2.0000 failed maximum 1.0000",
        "p95_latency_ms=2.0000 failed maximum 1.0000",
    ]
    assert aggregate_metrics(report.cases) == report.metrics


def test_evaluate_case_measures_context_uniqueness_and_relevant_retention() -> None:
    case = next(
        case
        for case in load_dataset(DATASET_PATH).cases
        if case.expected_result == "relevant_passages"
    )
    relevant = case.relevant_passages[0]

    def retrieve(_case, _limit):
        return [
            RetrievalCandidate(
                rank=1,
                document_key=relevant.document_key,
                filename="relevant.txt",
                chunk_id=1,
                chunk_index=0,
                passage_label=relevant.passage_label,
                score=0.9,
                document_id=1,
                content="same text",
                char_start=0,
                char_end=9,
            ),
            RetrievalCandidate(
                rank=2,
                document_key="irrelevant-document",
                filename="irrelevant.txt",
                chunk_id=2,
                chunk_index=0,
                passage_label="irrelevant-passage",
                score=0.8,
                document_id=2,
                content="same text",
                char_start=0,
                char_end=9,
            ),
        ], 1.0

    result = evaluate_case(case, retrieve, 5)

    assert result.unique_context_ratio == 0.5
    assert result.relevant_context_retention == 1.0
