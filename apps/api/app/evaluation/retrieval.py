from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.document import Document, DocumentChunk
from app.models.user import User
from app.services.document_ingestion import ExtractedDocument, SourceSpan, chunk_text
from app.services.embeddings import (
    EmbeddingProvider,
    search_document_chunks,
    validate_embeddings,
)

SCHEMA_VERSION = "1.0"


class EvaluationManifest(BaseModel):
    record_type: Literal["manifest"] = "manifest"
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    description: str = ""
    corpus_version: str = Field(min_length=1)
    chunking_version: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    embedding_model_revision: str = Field(min_length=1)
    embedding_dimensions: int = Field(gt=0)
    embedding_preprocessing: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    generator_model: str = Field(min_length=1)
    evaluator_version: str = Field(min_length=1)


class CorpusPassage(BaseModel):
    label: str = Field(min_length=1)
    text: str = Field(min_length=1)


class CorpusDocument(BaseModel):
    record_type: Literal["document"] = "document"
    document_key: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    language: Literal["en", "tr"]
    access: Literal["evaluation_user", "restricted"] = "evaluation_user"
    passages: list[CorpusPassage] = Field(min_length=1)


class RelevantPassage(BaseModel):
    document_key: str = Field(min_length=1)
    passage_label: str = Field(min_length=1)


class EvaluationCase(BaseModel):
    record_type: Literal["case"] = "case"
    case_id: str = Field(min_length=1)
    language: Literal["en", "tr"]
    question: str = Field(min_length=1)
    expected_answer_facts: list[str] = Field(default_factory=list)
    relevant_passages: list[RelevantPassage] = Field(default_factory=list)
    expected_result: Literal["relevant_passages", "no_result"]
    category: Literal["answerable", "unanswerable", "ambiguous", "permission_restricted"]
    document_keys: list[str] | None = None


class EvaluationDataset(BaseModel):
    manifest: EvaluationManifest
    documents: list[CorpusDocument]
    cases: list[EvaluationCase]


class RetrievalCandidate(BaseModel):
    rank: int
    document_key: str
    filename: str
    chunk_id: int
    chunk_index: int
    passage_label: str | None
    score: float


class CaseResult(BaseModel):
    case_id: str
    language: str
    category: str
    expected_result: str
    latency_ms: float
    candidates: list[RetrievalCandidate]
    recall_at_k: float | None
    precision_at_k: float | None
    reciprocal_rank: float | None
    hit: bool | None
    no_result_correct: bool | None
    authorization_leak: bool


class AggregateMetrics(BaseModel):
    case_count: int
    relevant_case_count: int
    no_result_case_count: int
    recall_at_k: float
    precision_at_k: float
    mean_reciprocal_rank: float
    hit_rate: float
    no_result_accuracy: float
    authorization_leak_count: int
    mean_latency_ms: float
    p95_latency_ms: float


class EvaluationThresholds(BaseModel):
    min_recall_at_k: float | None = Field(default=None, ge=0, le=1)
    min_precision_at_k: float | None = Field(default=None, ge=0, le=1)
    min_mean_reciprocal_rank: float | None = Field(default=None, ge=0, le=1)
    min_hit_rate: float | None = Field(default=None, ge=0, le=1)
    min_no_result_accuracy: float | None = Field(default=None, ge=0, le=1)
    max_mean_latency_ms: float | None = Field(default=None, gt=0)
    max_authorization_leaks: int = Field(default=0, ge=0)


class EvaluationReport(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    dataset_id: str
    dataset_version: str
    corpus_version: str
    chunking_version: str
    embedding_model: str
    embedding_model_revision: str
    embedding_dimensions: int
    embedding_preprocessing: str
    evaluator_version: str
    retrieval_limit: int
    metrics: AggregateMetrics
    thresholds: EvaluationThresholds
    threshold_failures: list[str]
    cases: list[CaseResult]

    @property
    def passed(self) -> bool:
        return not self.threshold_failures


Retriever = Callable[[EvaluationCase, int], tuple[list[RetrievalCandidate], float]]


def load_dataset(path: Path) -> EvaluationDataset:
    manifests: list[EvaluationManifest] = []
    documents: list[CorpusDocument] = []
    cases: list[EvaluationCase] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
            record_type = payload.get("record_type")
            if record_type == "manifest":
                manifests.append(EvaluationManifest.model_validate(payload))
            elif record_type == "document":
                documents.append(CorpusDocument.model_validate(payload))
            elif record_type == "case":
                cases.append(EvaluationCase.model_validate(payload))
            else:
                raise ValueError(f"unknown record_type {record_type!r}")
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"Invalid evaluation record at {path}:{line_number}: {exc}") from exc

    if len(manifests) != 1:
        raise ValueError("Evaluation dataset must contain exactly one manifest record")
    if not documents or not cases:
        raise ValueError("Evaluation dataset must contain documents and cases")
    dataset = EvaluationDataset(manifest=manifests[0], documents=documents, cases=cases)
    validate_dataset_references(dataset)
    return dataset


def validate_dataset_references(dataset: EvaluationDataset) -> None:
    document_map = {document.document_key: document for document in dataset.documents}
    if len(document_map) != len(dataset.documents):
        raise ValueError("Evaluation document_key values must be unique")
    case_ids = {case.case_id for case in dataset.cases}
    if len(case_ids) != len(dataset.cases):
        raise ValueError("Evaluation case_id values must be unique")

    passage_keys = {
        (document.document_key, passage.label)
        for document in dataset.documents
        for passage in document.passages
    }
    for case in dataset.cases:
        if case.expected_result == "relevant_passages" and not case.relevant_passages:
            raise ValueError(f"Case {case.case_id} requires at least one relevant passage")
        for relevant in case.relevant_passages:
            if (relevant.document_key, relevant.passage_label) not in passage_keys:
                raise ValueError(
                    f"Case {case.case_id} references unknown passage "
                    f"{relevant.document_key}/{relevant.passage_label}"
                )
        for document_key in case.document_keys or []:
            if document_key not in document_map:
                raise ValueError(f"Case {case.case_id} filters on unknown document {document_key}")


def prepare_corpus(
    db: Session,
    dataset: EvaluationDataset,
    *,
    provider: EmbeddingProvider,
    settings: Settings,
) -> tuple[int, dict[int, str], dict[str, int]]:
    identity = f"{dataset.manifest.dataset_id}-{dataset.manifest.dataset_version}"
    evaluation_email = f"evaluation+{identity}@offline.invalid"
    restricted_email = f"evaluation-restricted+{identity}@offline.invalid"
    for email in (evaluation_email, restricted_email):
        existing = db.scalar(select(User).where(User.email == email))
        if existing is not None:
            db.delete(existing)
    db.commit()

    evaluation_user = User(email=evaluation_email, password_hash="evaluation-only", is_active=True)
    restricted_user = User(email=restricted_email, password_hash="evaluation-only", is_active=True)
    db.add_all([evaluation_user, restricted_user])
    db.flush()

    key_by_document_id: dict[int, str] = {}
    id_by_document_key: dict[str, int] = {}
    for corpus_document in dataset.documents:
        content, spans = render_document(corpus_document)
        owner = evaluation_user if corpus_document.access == "evaluation_user" else restricted_user
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        document = Document(
            owner_id=owner.id,
            original_filename=corpus_document.filename,
            content_type="text/plain",
            size_bytes=len(content.encode("utf-8")),
            storage_path=f"evaluation://{identity}/{corpus_document.document_key}",
            checksum_sha256=checksum,
            status="ready",
        )
        db.add(document)
        db.flush()

        chunks = chunk_text(
            ExtractedDocument(text=content, source_spans=spans),
            chunk_size_chars=settings.document_chunk_size_chars,
            overlap_chars=settings.document_chunk_overlap_chars,
        )
        embeddings = provider.embed_texts([chunk.content for chunk in chunks])
        validate_embeddings(embeddings, expected_count=len(chunks), dimensions=provider.dimensions)
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            db.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=chunk.content,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    token_start=chunk.token_start,
                    token_end=chunk.token_end,
                    source_page=chunk.source_page,
                    source_label=chunk.source_label,
                    embedding=embedding,
                    embedding_model=provider.model,
                )
            )
        document.chunk_count = len(chunks)
        key_by_document_id[document.id] = corpus_document.document_key
        id_by_document_key[corpus_document.document_key] = document.id
    db.commit()
    return evaluation_user.id, key_by_document_id, id_by_document_key


def render_document(document: CorpusDocument) -> tuple[str, list[SourceSpan]]:
    parts: list[str] = []
    spans: list[SourceSpan] = []
    cursor = 0
    for passage in document.passages:
        if parts:
            parts.append("\n\n")
            cursor += 2
        start = cursor
        parts.append(passage.text)
        cursor += len(passage.text)
        spans.append(SourceSpan(start, cursor, source_label=passage.label))
    return "".join(parts), spans


def build_database_retriever(
    db: Session,
    *,
    user_id: int,
    provider: EmbeddingProvider,
    key_by_document_id: dict[int, str],
    id_by_document_key: dict[str, int],
) -> Retriever:
    def retrieve(case: EvaluationCase, limit: int) -> tuple[list[RetrievalCandidate], float]:
        document_ids = (
            [id_by_document_key[key] for key in case.document_keys]
            if case.document_keys is not None
            else None
        )
        started_at = perf_counter()
        results = search_document_chunks(
            db,
            user_id=user_id,
            query=case.question,
            limit=limit,
            provider=provider,
            document_ids=document_ids,
        )
        latency_ms = (perf_counter() - started_at) * 1000
        candidates = [
            RetrievalCandidate(
                rank=rank,
                document_key=key_by_document_id[chunk.document_id],
                filename=chunk.document.original_filename,
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                passage_label=chunk.source_label,
                score=score,
            )
            for rank, (chunk, score) in enumerate(results, start=1)
        ]
        return candidates, latency_ms

    return retrieve


def evaluate_dataset(
    dataset: EvaluationDataset,
    *,
    retrieve: Retriever,
    retrieval_limit: int,
    thresholds: EvaluationThresholds,
    embedding_model: str,
) -> EvaluationReport:
    case_results = [evaluate_case(case, retrieve, retrieval_limit) for case in dataset.cases]
    metrics = aggregate_metrics(case_results)
    failures = threshold_failures(metrics, thresholds)
    return EvaluationReport(
        generated_at=datetime.now(UTC),
        dataset_id=dataset.manifest.dataset_id,
        dataset_version=dataset.manifest.dataset_version,
        corpus_version=dataset.manifest.corpus_version,
        chunking_version=dataset.manifest.chunking_version,
        embedding_model=embedding_model,
        embedding_model_revision=dataset.manifest.embedding_model_revision,
        embedding_dimensions=dataset.manifest.embedding_dimensions,
        embedding_preprocessing=dataset.manifest.embedding_preprocessing,
        evaluator_version=dataset.manifest.evaluator_version,
        retrieval_limit=retrieval_limit,
        metrics=metrics,
        thresholds=thresholds,
        threshold_failures=failures,
        cases=case_results,
    )


def evaluate_case(case: EvaluationCase, retrieve: Retriever, limit: int) -> CaseResult:
    candidates, latency_ms = retrieve(case, limit)
    expected = {(item.document_key, item.passage_label) for item in case.relevant_passages}
    matching_ranks = [
        candidate.rank
        for candidate in candidates
        if (candidate.document_key, candidate.passage_label) in expected
    ]
    authorization_leak = case.category == "permission_restricted" and bool(candidates)
    recall: float | None
    precision: float | None
    reciprocal_rank: float | None
    hit: bool | None
    no_result_correct: bool | None
    if case.expected_result == "relevant_passages":
        match_count = len(matching_ranks)
        recall = match_count / len(expected)
        precision = match_count / len(candidates) if candidates else 0.0
        reciprocal_rank = 1 / min(matching_ranks) if matching_ranks else 0.0
        hit = bool(matching_ranks)
        no_result_correct = None
    else:
        recall = precision = reciprocal_rank = None
        hit = None
        no_result_correct = not candidates
    return CaseResult(
        case_id=case.case_id,
        language=case.language,
        category=case.category,
        expected_result=case.expected_result,
        latency_ms=latency_ms,
        candidates=candidates,
        recall_at_k=recall,
        precision_at_k=precision,
        reciprocal_rank=reciprocal_rank,
        hit=hit,
        no_result_correct=no_result_correct,
        authorization_leak=authorization_leak,
    )


def aggregate_metrics(results: list[CaseResult]) -> AggregateMetrics:
    relevant = [result for result in results if result.recall_at_k is not None]
    no_result = [result for result in results if result.no_result_correct is not None]
    recalls = [result.recall_at_k for result in relevant if result.recall_at_k is not None]
    precisions = [result.precision_at_k for result in relevant if result.precision_at_k is not None]
    reciprocal_ranks = [
        result.reciprocal_rank for result in relevant if result.reciprocal_rank is not None
    ]
    hits = [result.hit for result in relevant if result.hit is not None]
    no_result_outcomes = [
        result.no_result_correct for result in no_result if result.no_result_correct is not None
    ]
    latencies = sorted(result.latency_ms for result in results)
    p95_index = max(0, min(len(latencies) - 1, int(len(latencies) * 0.95)))
    return AggregateMetrics(
        case_count=len(results),
        relevant_case_count=len(relevant),
        no_result_case_count=len(no_result),
        recall_at_k=mean(recalls) if recalls else 0.0,
        precision_at_k=mean(precisions) if precisions else 0.0,
        mean_reciprocal_rank=mean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        hit_rate=mean(float(hit) for hit in hits) if hits else 0.0,
        no_result_accuracy=(
            mean(float(outcome) for outcome in no_result_outcomes) if no_result_outcomes else 0.0
        ),
        authorization_leak_count=sum(result.authorization_leak for result in results),
        mean_latency_ms=mean(latencies) if latencies else 0.0,
        p95_latency_ms=latencies[p95_index] if latencies else 0.0,
    )


def threshold_failures(metrics: AggregateMetrics, thresholds: EvaluationThresholds) -> list[str]:
    checks = (
        ("recall_at_k", metrics.recall_at_k, thresholds.min_recall_at_k, "minimum"),
        ("precision_at_k", metrics.precision_at_k, thresholds.min_precision_at_k, "minimum"),
        (
            "mean_reciprocal_rank",
            metrics.mean_reciprocal_rank,
            thresholds.min_mean_reciprocal_rank,
            "minimum",
        ),
        ("hit_rate", metrics.hit_rate, thresholds.min_hit_rate, "minimum"),
        (
            "no_result_accuracy",
            metrics.no_result_accuracy,
            thresholds.min_no_result_accuracy,
            "minimum",
        ),
        ("mean_latency_ms", metrics.mean_latency_ms, thresholds.max_mean_latency_ms, "maximum"),
    )
    failures = []
    for name, actual, threshold, direction in checks:
        if threshold is None:
            continue
        failed = actual < threshold if direction == "minimum" else actual > threshold
        if failed:
            failures.append(f"{name}={actual:.4f} failed {direction} {threshold:.4f}")
    if metrics.authorization_leak_count > thresholds.max_authorization_leaks:
        failures.append(
            f"authorization_leak_count={metrics.authorization_leak_count} exceeded maximum "
            f"{thresholds.max_authorization_leaks}"
        )
    return failures


def write_report(report: EvaluationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def format_summary(report: EvaluationReport) -> str:
    metrics = report.metrics
    status = "PASSED" if report.passed else "FAILED"
    lines = [
        f"Dense retrieval evaluation: {status}",
        f"Dataset: {report.dataset_id} {report.dataset_version}",
        f"Embedding model: {report.embedding_model}",
        f"Cases: {metrics.case_count} ({metrics.relevant_case_count} relevant, "
        f"{metrics.no_result_case_count} no-result)",
        f"Recall@{report.retrieval_limit}: {metrics.recall_at_k:.3f}",
        f"Precision@{report.retrieval_limit}: {metrics.precision_at_k:.3f}",
        f"MRR: {metrics.mean_reciprocal_rank:.3f}",
        f"Hit rate: {metrics.hit_rate:.3f}",
        f"No-result accuracy: {metrics.no_result_accuracy:.3f}",
        f"Authorization leaks: {metrics.authorization_leak_count}",
        f"Latency mean/p95: {metrics.mean_latency_ms:.1f}/{metrics.p95_latency_ms:.1f} ms",
    ]
    lines.extend(f"Threshold failure: {failure}" for failure in report.threshold_failures)
    return "\n".join(lines)
