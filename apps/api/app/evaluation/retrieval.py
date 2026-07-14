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
from app.retrieval import (
    RetrievalCandidate as RuntimeRetrievalCandidate,
    RetrievalQuery,
    RetrievalStrategy,
    relevant_context_retention,
    select_context,
)
from app.services.document_ingestion import ExtractedDocument, SourceSpan, chunk_text
from app.services.embeddings import (
    EmbeddingProvider,
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
    strategy: str = "dense"
    strategy_ranks: dict[str, int] = Field(default_factory=dict)
    strategy_scores: dict[str, float] = Field(default_factory=dict)
    document_id: int = Field(default=0, exclude=True)
    content: str = Field(default="", exclude=True)
    char_start: int = Field(default=0, exclude=True)
    char_end: int = Field(default=0, exclude=True)


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
    unique_context_ratio: float | None = None
    relevant_context_retention: float | None = None


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
    mean_unique_context_ratio: float = 1.0
    mean_relevant_context_retention: float = 1.0


class EvaluationThresholds(BaseModel):
    min_recall_at_k: float | None = Field(default=None, ge=0, le=1)
    min_precision_at_k: float | None = Field(default=None, ge=0, le=1)
    min_mean_reciprocal_rank: float | None = Field(default=None, ge=0, le=1)
    min_hit_rate: float | None = Field(default=None, ge=0, le=1)
    min_no_result_accuracy: float | None = Field(default=None, ge=0, le=1)
    max_mean_latency_ms: float | None = Field(default=None, gt=0)
    max_p95_latency_ms: float | None = Field(default=None, gt=0)
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
    retrieval_strategy: str = "dense"
    reranker_model: str | None = None
    reranker_model_revision: str | None = None
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
    provider: EmbeddingProvider | None,
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
        embeddings = provider.embed_texts([chunk.content for chunk in chunks]) if provider else None
        if provider is not None and embeddings is not None:
            validate_embeddings(
                embeddings,
                expected_count=len(chunks),
                dimensions=provider.dimensions,
            )
        for index, chunk in enumerate(chunks):
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
                    embedding=embeddings[index] if embeddings is not None else None,
                    embedding_model=provider.model if provider is not None else None,
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
    strategy: RetrievalStrategy,
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
        retrieval_result = strategy.retrieve(
            db,
            RetrievalQuery(
                user_id=user_id,
                text=case.question,
                limit=limit,
                document_ids=tuple(document_ids) if document_ids is not None else None,
            ),
        )
        latency_ms = (perf_counter() - started_at) * 1000
        evaluation_candidates = [
            RetrievalCandidate(
                rank=candidate.rank,
                document_key=key_by_document_id[candidate.document_id],
                filename=candidate.document_filename,
                chunk_id=candidate.chunk_id,
                chunk_index=candidate.chunk_index,
                passage_label=candidate.source_label,
                score=candidate.normalized_score,
                strategy=candidate.strategy,
                strategy_ranks=candidate.strategy_ranks,
                strategy_scores=candidate.strategy_scores,
                document_id=candidate.document_id,
                content=candidate.content,
                char_start=candidate.char_start,
                char_end=candidate.char_end,
            )
            for candidate in retrieval_result.candidates
        ]
        return evaluation_candidates, latency_ms

    return retrieve


def evaluate_dataset(
    dataset: EvaluationDataset,
    *,
    retrieve: Retriever,
    retrieval_limit: int,
    thresholds: EvaluationThresholds,
    embedding_model: str,
    retrieval_strategy: str = "dense",
    max_context_chars: int = 12_000,
    max_context_chars_per_document: int = 6_000,
    reranker_model: str | None = None,
    reranker_model_revision: str | None = None,
) -> EvaluationReport:
    case_results = [
        evaluate_case(
            case,
            retrieve,
            retrieval_limit,
            max_context_chars=max_context_chars,
            max_context_chars_per_document=max_context_chars_per_document,
        )
        for case in dataset.cases
    ]
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
        retrieval_strategy=retrieval_strategy,
        reranker_model=reranker_model,
        reranker_model_revision=reranker_model_revision,
        retrieval_limit=retrieval_limit,
        metrics=metrics,
        thresholds=thresholds,
        threshold_failures=failures,
        cases=case_results,
    )


def evaluate_case(
    case: EvaluationCase,
    retrieve: Retriever,
    limit: int,
    *,
    max_context_chars: int = 12_000,
    max_context_chars_per_document: int = 6_000,
) -> CaseResult:
    candidates, latency_ms = retrieve(case, limit)
    expected = {(item.document_key, item.passage_label) for item in case.relevant_passages}
    matching_ranks = [
        candidate.rank
        for candidate in candidates
        if (candidate.document_key, candidate.passage_label) in expected
    ]
    authorization_leak = case.category == "permission_restricted" and bool(candidates)
    unique_context_ratio: float | None = None
    context_retention: float | None = None
    if candidates and all(candidate.content for candidate in candidates):
        selection = select_context(
            [evaluation_candidate_to_runtime(candidate) for candidate in candidates],
            max_chars=max_context_chars,
            max_chars_per_document=max_context_chars_per_document,
        )
        unique_context_ratio = selection.metrics.unique_context_ratio
        relevant_chunk_ids = {
            candidate.chunk_id
            for candidate in candidates
            if (candidate.document_key, candidate.passage_label) in expected
        }
        context_retention = relevant_context_retention(
            selection.candidates,
            relevant_chunk_ids,
        )
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
        unique_context_ratio=unique_context_ratio,
        relevant_context_retention=context_retention,
    )


def evaluation_candidate_to_runtime(candidate: RetrievalCandidate) -> RuntimeRetrievalCandidate:
    return RuntimeRetrievalCandidate(
        document_id=candidate.document_id,
        document_filename=candidate.filename,
        chunk_id=candidate.chunk_id,
        chunk_index=candidate.chunk_index,
        content=candidate.content,
        source_page=None,
        source_label=candidate.passage_label,
        char_start=candidate.char_start,
        char_end=candidate.char_end,
        raw_score=candidate.score,
        normalized_score=candidate.score,
        rank=candidate.rank,
        strategy=candidate.strategy,
        strategy_ranks=candidate.strategy_ranks,
        strategy_scores=candidate.strategy_scores,
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
    unique_context_ratios = [
        result.unique_context_ratio
        for result in results
        if result.unique_context_ratio is not None
    ]
    context_retentions = [
        result.relevant_context_retention
        for result in relevant
        if result.relevant_context_retention is not None
    ]
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
        mean_unique_context_ratio=(
            mean(unique_context_ratios) if unique_context_ratios else 1.0
        ),
        mean_relevant_context_retention=(
            mean(context_retentions) if context_retentions else 1.0
        ),
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
        ("p95_latency_ms", metrics.p95_latency_ms, thresholds.max_p95_latency_ms, "maximum"),
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
    model_summary = {
        "dense": f"Embedding model: {report.embedding_model}",
        "lexical": "Text search configuration: PostgreSQL simple",
        "hybrid": (
            f"Embedding model: {report.embedding_model}; "
            "text search configuration: PostgreSQL simple"
        ),
        "reranked": (
            f"Embedding model: {report.embedding_model}; reranker: "
            f"{report.reranker_model}@{report.reranker_model_revision}"
        ),
    }.get(report.retrieval_strategy, f"Embedding model: {report.embedding_model}")
    lines = [
        f"{report.retrieval_strategy.title()} retrieval evaluation: {status}",
        f"Dataset: {report.dataset_id} {report.dataset_version}",
        model_summary,
        f"Cases: {metrics.case_count} ({metrics.relevant_case_count} relevant, "
        f"{metrics.no_result_case_count} no-result)",
        f"Recall@{report.retrieval_limit}: {metrics.recall_at_k:.3f}",
        f"Precision@{report.retrieval_limit}: {metrics.precision_at_k:.3f}",
        f"MRR: {metrics.mean_reciprocal_rank:.3f}",
        f"Hit rate: {metrics.hit_rate:.3f}",
        f"No-result accuracy: {metrics.no_result_accuracy:.3f}",
        f"Authorization leaks: {metrics.authorization_leak_count}",
        f"Unique context ratio: {metrics.mean_unique_context_ratio:.3f}",
        f"Relevant context retention: {metrics.mean_relevant_context_retention:.3f}",
        f"Latency mean/p95: {metrics.mean_latency_ms:.1f}/{metrics.p95_latency_ms:.1f} ms",
    ]
    lines.extend(f"Threshold failure: {failure}" for failure in report.threshold_failures)
    return "\n".join(lines)
