from collections import Counter
import json
from pathlib import Path

import pytest

from app.evaluation.retrieval import (
    EvaluationReport,
    EvaluationThresholds,
    RetrievalCandidate,
    aggregate_metrics,
    evaluate_dataset,
    load_dataset,
)


ROOT = Path(__file__).resolve().parents[3]
DATASET_PATH = ROOT / "evaluation" / "datasets" / "dense-baseline-smoke-v1.jsonl"
FORMAL_DATASET_PATH = ROOT / "evaluation" / "datasets" / "dense-baseline-v1.jsonl"
BASELINE_REPORT_PATH = ROOT / "evaluation" / "baselines" / "dense-baseline-v1.json"


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
    assert report.threshold_failures == []
    assert report.passed is True


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
        thresholds=EvaluationThresholds(min_recall_at_k=1.0, max_mean_latency_ms=1.0),
        embedding_model="fake-bow",
    )

    assert report.metrics.recall_at_k == 1.0
    assert report.metrics.no_result_accuracy == 1.0
    assert report.metrics.authorization_leak_count == 0
    assert report.passed is False
    assert report.threshold_failures == ["mean_latency_ms=2.0000 failed maximum 1.0000"]
    assert aggregate_metrics(report.cases) == report.metrics
