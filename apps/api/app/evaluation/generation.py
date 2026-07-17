from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import re
from statistics import mean
from time import perf_counter
from typing import Any, Literal, Self, TypedDict
import unicodedata
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.config import Settings
from app.evaluation.retrieval import EvaluationCase, EvaluationDataset
from app.retrieval import (
    RetrievalQuery,
    RetrievalStrategy,
    build_grounded_system_message,
    select_context,
)
from app.schemas.chat import ChatCompletionRequest, ChatMessage, ChatUsage
from app.services.llm import LLMBackend, estimate_tokens


GENERATION_PROMPT_VERSION = "grounded-natural-citations-v1"
SOURCE_CITATION_RE = re.compile(r"\[Source\s+(\d+)(?::[^\]]+)?\]", re.IGNORECASE)
REFUSAL_PATTERNS = (
    "do not provide",
    "does not provide",
    "not provided",
    "not specified",
    "cannot answer",
    "unable to answer",
    "lack the information",
    "does not contain the answer",
    "do not have the answer",
    "do not have enough information",
    "not enough information",
    "no accessible document",
    "yeterli bilgi bulunmuyor",
    "yeterli bilgi yok",
    "cevabi verilmedi",
    "belirtilmem",
    "bulunmam",
    "bilgi yok",
    "yanitlanamaz",
    "cevaplanamaz",
)
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is",
    "it", "of", "on", "or", "the", "to", "with", "bir", "bu", "da", "de", "icin",
    "ile", "ve", "veya",
}
NUMBER_ALIASES = {
    "five": "5", "six": "6", "seven": "7", "fifteen": "15", "twenty": "20",
    "thirty": "30", "fifty": "50", "ninety": "90", "bes": "5", "alti": "6",
    "yedi": "7", "onbes": "15", "yirmi": "20", "otuz": "30", "elli": "50",
    "doksan": "90",
}


class GenerationClaim(BaseModel):
    text: str = Field(min_length=1)
    source_numbers: list[int] = Field(default_factory=list)
    evidence_quote: str = ""


class GeneratedAnswer(BaseModel):
    answer: str
    claims: list[GenerationClaim] = Field(default_factory=list)
    refusal: bool


@dataclass(frozen=True, slots=True)
class AnswerScores:
    expected_fact_coverage: float | None
    citation_accuracy: float | None
    citation_coverage: float | None
    faithfulness: float | None
    hallucination_rate: float | None
    refusal_correct: bool | None
    restricted_fact_leak: bool


class TaskBehaviorScores(TypedDict):
    language_adherent: bool | None
    citation_format_valid: bool | None
    json_schema_valid: bool | None
    incident_report_structure_valid: bool | None
    terminology_consistent: bool | None
    supported_refusal: bool | None


class GenerationCaseResult(BaseModel):
    case_id: str
    language: str
    category: str
    expected_result: str
    answer: str
    refusal: bool
    parse_success: bool
    source_count: int
    expected_fact_coverage: float | None
    citation_accuracy: float | None
    citation_coverage: float | None
    faithfulness: float | None
    hallucination_rate: float | None
    refusal_correct: bool | None
    restricted_fact_leak: bool
    retrieval_latency_ms: float
    time_to_first_token_ms: float
    end_to_end_latency_ms: float
    completion_tokens: int
    tokens_per_second: float
    task: str = "grounded_answer"
    language_adherent: bool | None = None
    citation_format_valid: bool | None = None
    json_schema_valid: bool | None = None
    incident_report_structure_valid: bool | None = None
    terminology_consistent: bool | None = None
    supported_refusal: bool | None = None
    answer_persisted: bool = True


class GenerationMetrics(BaseModel):
    case_count: int
    relevant_case_count: int
    no_result_case_count: int
    parse_success_rate: float
    expected_fact_coverage: float
    citation_accuracy: float
    citation_coverage: float
    answer_faithfulness: float
    hallucination_rate: float
    refusal_accuracy: float
    restricted_fact_leak_count: int
    mean_time_to_first_token_ms: float
    p95_time_to_first_token_ms: float
    mean_end_to_end_latency_ms: float
    p95_end_to_end_latency_ms: float
    mean_tokens_per_second: float


class GenerationThresholds(BaseModel):
    min_parse_success_rate: float | None = Field(default=None, ge=0, le=1)
    min_expected_fact_coverage: float | None = Field(default=None, ge=0, le=1)
    min_citation_accuracy: float | None = Field(default=None, ge=0, le=1)
    min_citation_coverage: float | None = Field(default=None, ge=0, le=1)
    min_answer_faithfulness: float | None = Field(default=None, ge=0, le=1)
    max_hallucination_rate: float | None = Field(default=None, ge=0, le=1)
    min_refusal_accuracy: float | None = Field(default=None, ge=0, le=1)
    max_restricted_fact_leaks: int = Field(default=0, ge=0)
    max_mean_time_to_first_token_ms: float | None = Field(default=None, gt=0)
    max_p95_time_to_first_token_ms: float | None = Field(default=None, gt=0)
    max_mean_end_to_end_latency_ms: float | None = Field(default=None, gt=0)
    max_p95_end_to_end_latency_ms: float | None = Field(default=None, gt=0)
    min_mean_tokens_per_second: float | None = Field(default=None, gt=0)


class GenerationReport(BaseModel):
    schema_version: str = "1.0"
    report_type: Literal["production_runtime_evaluation"] = "production_runtime_evaluation"
    evaluation_mode: Literal["base", "base_rag", "adapter", "adapter_rag"] = "base_rag"
    adapter_id: str | None = None
    content_policy: Literal["public", "restricted"] = "public"
    case_output_policy: Literal["reviewable", "redacted"] = "reviewable"
    generated_at: datetime
    dataset_id: str
    dataset_version: str
    corpus_version: str
    embedding_model: str
    embedding_model_revision: str
    generator_model: str
    generator_model_revision: str
    prompt_version: str = GENERATION_PROMPT_VERSION
    retrieval_strategy: str
    retrieval_limit: int
    metrics: GenerationMetrics
    thresholds: GenerationThresholds
    threshold_failures: list[str]
    cases: list[GenerationCaseResult]

    @model_validator(mode="after")
    def validate_output_policy(self) -> Self:
        if self.content_policy == "restricted":
            if self.case_output_policy != "redacted":
                raise ValueError("restricted report content requires case_output_policy=redacted")
            if any(case.answer or case.answer_persisted for case in self.cases):
                raise ValueError("restricted report cases must not persist answer text")
        return self

    @property
    def passed(self) -> bool:
        return not self.threshold_failures


def evaluate_generation_dataset(
    dataset: EvaluationDataset,
    *,
    db: Session | None,
    user_id: int | None,
    strategy: RetrievalStrategy | None,
    backend: LLMBackend,
    settings: Settings,
    thresholds: GenerationThresholds,
    retrieval_limit: int,
    id_by_document_key: dict[str, int] | None,
    evaluation_mode: Literal["base", "base_rag", "adapter", "adapter_rag"] = "base_rag",
) -> GenerationReport:
    rag_enabled = evaluation_mode in {"base_rag", "adapter_rag"}
    adapter_enabled = evaluation_mode in {"adapter", "adapter_rag"}
    if rag_enabled and (
        db is None or user_id is None or strategy is None or id_by_document_key is None
    ):
        raise ValueError(f"{evaluation_mode} evaluation requires database-backed retrieval inputs")
    if not rag_enabled and strategy is not None:
        raise ValueError(f"{evaluation_mode} evaluation must not receive a retrieval strategy")
    if adapter_enabled and not settings.llm_adapter_id:
        raise ValueError(f"{evaluation_mode} evaluation requires LLM_ADAPTER_ID")
    if not adapter_enabled and settings.llm_adapter_id:
        raise ValueError(f"{evaluation_mode} evaluation requires an adapter-free runtime")
    results = [
        evaluate_generation_case(
            case,
            db=db,
            user_id=user_id,
            strategy=strategy,
            backend=backend,
            settings=settings,
            retrieval_limit=retrieval_limit,
            id_by_document_key=id_by_document_key,
        )
        for case in dataset.cases
    ]
    metrics = aggregate_generation_metrics(results)
    persisted_results = apply_case_output_policy(
        results,
        policy=dataset.manifest.case_output_policy,
    )
    return GenerationReport(
        generated_at=datetime.now(UTC),
        dataset_id=dataset.manifest.dataset_id,
        dataset_version=dataset.manifest.dataset_version,
        corpus_version=dataset.manifest.corpus_version,
        embedding_model=settings.embedding_model,
        embedding_model_revision=dataset.manifest.embedding_model_revision,
        generator_model=settings.llm_model,
        generator_model_revision=settings.llm_model_revision,
        evaluation_mode=evaluation_mode,
        adapter_id=settings.llm_adapter_id if adapter_enabled else None,
        content_policy=dataset.manifest.content_policy,
        case_output_policy=dataset.manifest.case_output_policy,
        retrieval_strategy=strategy.name if strategy is not None else "none",
        retrieval_limit=retrieval_limit,
        metrics=metrics,
        thresholds=thresholds,
        threshold_failures=generation_threshold_failures(metrics, thresholds),
        cases=persisted_results,
    )


def apply_case_output_policy(
    results: list[GenerationCaseResult],
    *,
    policy: Literal["reviewable", "redacted"],
) -> list[GenerationCaseResult]:
    if policy == "reviewable":
        return results
    return [
        result.model_copy(update={"answer": "", "answer_persisted": False})
        for result in results
    ]


def evaluate_generation_case(
    case: EvaluationCase,
    *,
    db: Session | None,
    user_id: int | None,
    strategy: RetrievalStrategy | None,
    backend: LLMBackend,
    settings: Settings,
    retrieval_limit: int,
    id_by_document_key: dict[str, int] | None,
) -> GenerationCaseResult:
    total_started_at = perf_counter()
    source_contents: list[str] = []
    source_count = 0
    retrieval_latency_ms = 0.0
    context = ""
    if strategy is not None:
        if db is None or user_id is None or id_by_document_key is None:
            raise ValueError("retrieval evaluation inputs are incomplete")
        retrieval_started_at = perf_counter()
        retrieval_result = strategy.retrieve(
            db,
            RetrievalQuery(
                user_id=user_id,
                text=case.question,
                limit=retrieval_limit,
                document_ids=(
                    tuple(id_by_document_key[key] for key in case.document_keys)
                    if case.document_keys is not None
                    else None
                ),
            ),
        )
        retrieval_latency_ms = elapsed_ms(retrieval_started_at)
        selection = select_context(
            retrieval_result.candidates,
            max_chars=settings.rag_max_context_chars,
            max_chars_per_document=settings.rag_max_context_chars_per_document,
        )
        context = selection.context
        source_contents = [candidate.content for candidate in selection.candidates]
        source_count = len(selection.candidates)
    request = build_generation_request(
        case,
        context,
        settings.llm_model,
        rag_enabled=strategy is not None,
    )
    content, usage, ttft_ms, generation_ms = collect_stream(backend, request)
    generated, parse_success = parse_generated_answer(content)
    result = score_generated_answer(
        case,
        generated,
        source_contents,
    )
    completion_tokens = usage.completion_tokens if usage else estimate_tokens(content)
    task = case.task or (
        "grounded_refusal" if case.expected_result == "no_result" else "grounded_answer"
    )
    task_scores = score_task_behavior(case, generated, result)
    return GenerationCaseResult(
        case_id=case.case_id,
        language=case.language,
        category=case.category,
        expected_result=case.expected_result,
        answer=generated.answer,
        refusal=generated.refusal,
        parse_success=parse_success,
        source_count=source_count,
        retrieval_latency_ms=round(retrieval_latency_ms, 3),
        time_to_first_token_ms=round(ttft_ms, 3),
        end_to_end_latency_ms=round(elapsed_ms(total_started_at), 3),
        completion_tokens=completion_tokens,
        tokens_per_second=round(completion_tokens / max(generation_ms / 1000, 0.001), 3),
        task=task,
        **task_scores,
        expected_fact_coverage=result.expected_fact_coverage,
        citation_accuracy=result.citation_accuracy,
        citation_coverage=result.citation_coverage,
        faithfulness=result.faithfulness,
        hallucination_rate=result.hallucination_rate,
        refusal_correct=result.refusal_correct,
        restricted_fact_leak=result.restricted_fact_leak,
    )


def score_task_behavior(
    case: EvaluationCase,
    generated: GeneratedAnswer,
    answer_scores: AnswerScores,
) -> TaskBehaviorScores:
    task = case.task or (
        "grounded_refusal" if case.expected_result == "no_result" else "grounded_answer"
    )
    return {
        "language_adherent": answer_uses_language(generated.answer, case.language),
        "citation_format_valid": (
            citation_format_is_valid(generated.answer)
            if task != "grounded_refusal"
            else None
        ),
        "json_schema_valid": (
            json_answer_matches_schema(generated.answer, case.target_json_schema)
            if task == "json_output"
            else None
        ),
        "incident_report_structure_valid": (
            incident_report_has_sections(generated.answer, case.required_incident_sections)
            if task == "incident_report"
            else None
        ),
        "terminology_consistent": (
            terminology_is_consistent(
                generated.answer,
                required=case.required_terms,
                forbidden=case.forbidden_terms,
            )
            if task == "terminology"
            else None
        ),
        "supported_refusal": (
            bool(answer_scores.refusal_correct) and not answer_scores.restricted_fact_leak
            if task == "grounded_refusal"
            else None
        ),
    }


def answer_uses_language(answer: str, language: str) -> bool:
    normalized = normalize_text(answer)
    if not normalized:
        return False
    words = set(normalized.split())
    english_markers = {"the", "is", "are", "and", "must", "does", "not", "within", "every"}
    turkish_markers = {"bir", "bu", "ve", "icin", "degil", "gerekir", "her", "icinde", "olarak"}
    english_score = len(words & english_markers)
    turkish_score = len(words & turkish_markers)
    has_turkish_character = bool(re.search(r"[çğıöşü]", answer.casefold()))
    if language == "tr":
        return has_turkish_character or turkish_score >= english_score
    return not has_turkish_character and english_score >= turkish_score


def citation_format_is_valid(answer: str) -> bool:
    source_like = re.findall(r"\[[^\]]*source[^\]]*\]", answer, flags=re.IGNORECASE)
    return bool(source_like) and all(SOURCE_CITATION_RE.fullmatch(item) for item in source_like)


def json_answer_matches_schema(answer: str, schema: dict[str, Any] | None) -> bool:
    if schema is None:
        return False
    payload = answer.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", payload, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        payload = fenced.group(1)
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return False
    return json_value_matches_schema(value, schema)


def json_value_matches_schema(value: Any, schema: dict[str, Any]) -> bool:
    if "enum" in schema and value not in schema["enum"]:
        return False
    expected_type = schema.get("type")
    type_matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    if isinstance(expected_type, str) and not type_matches.get(expected_type, False):
        return False
    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(field in value for field in required):
            return False
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return False
        if schema.get("additionalProperties") is False and any(
            field not in properties for field in value
        ):
            return False
        return all(
            not isinstance(properties.get(field), dict)
            or json_value_matches_schema(field_value, properties[field])
            for field, field_value in value.items()
            if field in properties
        )
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return all(json_value_matches_schema(item, schema["items"]) for item in value)
    return True


def incident_report_has_sections(answer: str, required_sections: list[str]) -> bool:
    if not required_sections:
        return False
    normalized = normalize_text(answer)
    return all(normalize_text(section) in normalized for section in required_sections)


def terminology_is_consistent(
    answer: str,
    *,
    required: list[str],
    forbidden: list[str],
) -> bool:
    if not required:
        return False
    normalized = normalize_text(answer)
    return all(normalize_text(term) in normalized for term in required) and not any(
        normalize_text(term) in normalized for term in forbidden
    )


def build_generation_request(
    case: EvaluationCase,
    context: str,
    model: str,
    *,
    rag_enabled: bool = True,
) -> ChatCompletionRequest:
    messages = [ChatMessage(role="user", content=case.question)]
    if rag_enabled:
        messages.insert(
            0,
            ChatMessage(
                role="system",
                content=build_grounded_system_message(context),
            ),
        )
    return ChatCompletionRequest(
        model=model,
        messages=messages,
        temperature=0,
        max_tokens=192,
        stream=True,
    )


def collect_stream(
    backend: LLMBackend,
    request: ChatCompletionRequest,
) -> tuple[str, ChatUsage | None, float, float]:
    started_at = perf_counter()
    first_content_at: float | None = None
    content_parts: list[str] = []
    usage: ChatUsage | None = None
    for event in backend.stream_chat(request):
        for line in event.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line.removeprefix("data:").strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("usage") is not None:
                usage = ChatUsage.model_validate(data["usage"])
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            delta = choices[0].get("delta", {})
            content = delta.get("content")
            if isinstance(content, str) and content:
                if first_content_at is None:
                    first_content_at = perf_counter()
                content_parts.append(content)
    completed_at = perf_counter()
    ttft_ms = ((first_content_at or completed_at) - started_at) * 1000
    return "".join(content_parts), usage, ttft_ms, (completed_at - started_at) * 1000


def parse_generated_answer(content: str) -> tuple[GeneratedAnswer, bool]:
    answer = content.strip()
    if not answer:
        return GeneratedAnswer(answer="", claims=[], refusal=False), False
    normalized_answer = normalize_text(answer)
    refusal = any(pattern in normalized_answer for pattern in REFUSAL_PATTERNS)
    claims = [] if refusal else extract_natural_claims(answer)
    return GeneratedAnswer(answer=answer, claims=claims, refusal=refusal), True


def extract_natural_claims(answer: str) -> list[GenerationClaim]:
    claims: list[GenerationClaim] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer):
        text = sentence.strip()
        if not text:
            continue
        source_numbers = [int(match) for match in SOURCE_CITATION_RE.findall(text)]
        evidence_text = SOURCE_CITATION_RE.sub("", text).strip()
        citation_prefix_removed = re.sub(
            r"^source\s*:?\s*$",
            "",
            evidence_text,
            flags=re.IGNORECASE,
        )
        if source_numbers and not content_tokens(citation_prefix_removed) and claims:
            previous = claims[-1]
            claims[-1] = previous.model_copy(
                update={
                    "source_numbers": list(
                        dict.fromkeys([*previous.source_numbers, *source_numbers])
                    )
                }
            )
            continue
        claims.append(
            GenerationClaim(
                text=text,
                source_numbers=source_numbers,
                evidence_quote=evidence_text,
            )
        )
    return claims


def score_generated_answer(
    case: EvaluationCase,
    generated: GeneratedAnswer,
    sources: list[str],
) -> AnswerScores:
    fact_hits = [fact_is_present(fact, generated.answer) for fact in case.expected_answer_facts]
    restricted_leak = case.category == "permission_restricted" and any(fact_hits)
    if case.expected_result == "no_result":
        return AnswerScores(
            expected_fact_coverage=None,
            citation_accuracy=None,
            citation_coverage=None,
            faithfulness=None,
            hallucination_rate=None,
            refusal_correct=generated.refusal,
            restricted_fact_leak=restricted_leak,
        )

    claims = generated.claims
    supported = [claim_is_supported(claim, sources) for claim in claims]
    cited = [bool(claim.source_numbers) for claim in claims]
    claim_count = len(claims)
    faithfulness = sum(supported) / claim_count if claim_count else 0.0
    cited_indexes = [index for index, has_citation in enumerate(cited) if has_citation]
    citation_accuracy = (
        sum(supported[index] for index in cited_indexes) / len(cited_indexes)
        if cited_indexes
        else 0.0
    )
    return AnswerScores(
        expected_fact_coverage=(
            sum(fact_hits) / len(fact_hits) if fact_hits else 1.0
        ),
        citation_accuracy=citation_accuracy,
        citation_coverage=sum(cited) / claim_count if claim_count else 0.0,
        faithfulness=faithfulness,
        hallucination_rate=1.0 - faithfulness,
        refusal_correct=None,
        restricted_fact_leak=restricted_leak,
    )


def claim_is_supported(claim: GenerationClaim, sources: list[str]) -> bool:
    claim_tokens = content_tokens(claim.evidence_quote)
    if not claim_tokens or not claim.source_numbers:
        return False
    return any(
        1 <= number <= len(sources)
        and len(claim_tokens & content_tokens(sources[number - 1])) / len(claim_tokens) >= 0.6
        for number in claim.source_numbers
    )


def content_tokens(text: str) -> set[str]:
    return {
        NUMBER_ALIASES.get(token, token)
        for token in normalize_text(text).split()
        if len(token) > 1 and token not in STOPWORDS
    }


def fact_is_present(fact: str, answer: str) -> bool:
    fact_tokens = content_tokens(fact)
    if not fact_tokens:
        return True
    answer_tokens = content_tokens(answer)
    return len(fact_tokens & answer_tokens) / len(fact_tokens) >= 0.6


def normalize_text(text: str) -> str:
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", text).casefold()
        if unicodedata.category(character) != "Mn"
    )
    return " ".join(re.sub(r"[^\w%:]+", " ", normalized).split())


def aggregate_generation_metrics(results: list[GenerationCaseResult]) -> GenerationMetrics:
    relevant = [result for result in results if result.expected_fact_coverage is not None]
    no_result = [result for result in results if result.refusal_correct is not None]
    ttft = sorted(result.time_to_first_token_ms for result in results)
    end_to_end = sorted(result.end_to_end_latency_ms for result in results)
    return GenerationMetrics(
        case_count=len(results),
        relevant_case_count=len(relevant),
        no_result_case_count=len(no_result),
        parse_success_rate=mean(float(result.parse_success) for result in results),
        expected_fact_coverage=mean_required(relevant, "expected_fact_coverage"),
        citation_accuracy=mean_required(relevant, "citation_accuracy"),
        citation_coverage=mean_required(relevant, "citation_coverage"),
        answer_faithfulness=mean_required(relevant, "faithfulness"),
        hallucination_rate=mean_required(relevant, "hallucination_rate"),
        refusal_accuracy=mean(
            float(result.refusal_correct) for result in no_result if result.refusal_correct is not None
        ),
        restricted_fact_leak_count=sum(result.restricted_fact_leak for result in results),
        mean_time_to_first_token_ms=mean(ttft),
        p95_time_to_first_token_ms=percentile_95(ttft),
        mean_end_to_end_latency_ms=mean(end_to_end),
        p95_end_to_end_latency_ms=percentile_95(end_to_end),
        mean_tokens_per_second=mean(result.tokens_per_second for result in results),
    )


def mean_required(results: list[GenerationCaseResult], field: str) -> float:
    values = [getattr(result, field) for result in results]
    return mean(value for value in values if value is not None) if values else 0.0


def percentile_95(values: list[float]) -> float:
    return values[max(0, min(len(values) - 1, int(len(values) * 0.95)))] if values else 0.0


def generation_threshold_failures(
    metrics: GenerationMetrics,
    thresholds: GenerationThresholds,
) -> list[str]:
    checks = (
        ("parse_success_rate", metrics.parse_success_rate, thresholds.min_parse_success_rate, "minimum"),
        ("expected_fact_coverage", metrics.expected_fact_coverage, thresholds.min_expected_fact_coverage, "minimum"),
        ("citation_accuracy", metrics.citation_accuracy, thresholds.min_citation_accuracy, "minimum"),
        ("citation_coverage", metrics.citation_coverage, thresholds.min_citation_coverage, "minimum"),
        ("answer_faithfulness", metrics.answer_faithfulness, thresholds.min_answer_faithfulness, "minimum"),
        ("hallucination_rate", metrics.hallucination_rate, thresholds.max_hallucination_rate, "maximum"),
        ("refusal_accuracy", metrics.refusal_accuracy, thresholds.min_refusal_accuracy, "minimum"),
        ("mean_time_to_first_token_ms", metrics.mean_time_to_first_token_ms, thresholds.max_mean_time_to_first_token_ms, "maximum"),
        ("p95_time_to_first_token_ms", metrics.p95_time_to_first_token_ms, thresholds.max_p95_time_to_first_token_ms, "maximum"),
        ("mean_end_to_end_latency_ms", metrics.mean_end_to_end_latency_ms, thresholds.max_mean_end_to_end_latency_ms, "maximum"),
        ("p95_end_to_end_latency_ms", metrics.p95_end_to_end_latency_ms, thresholds.max_p95_end_to_end_latency_ms, "maximum"),
        ("mean_tokens_per_second", metrics.mean_tokens_per_second, thresholds.min_mean_tokens_per_second, "minimum"),
    )
    failures: list[str] = []
    for name, actual, threshold, direction in checks:
        if threshold is None:
            continue
        failed = actual < threshold if direction == "minimum" else actual > threshold
        if failed:
            failures.append(f"{name}={actual:.4f} failed {direction} {threshold:.4f}")
    if metrics.restricted_fact_leak_count > thresholds.max_restricted_fact_leaks:
        failures.append(
            f"restricted_fact_leak_count={metrics.restricted_fact_leak_count} exceeded maximum "
            f"{thresholds.max_restricted_fact_leaks}"
        )
    return failures


def format_generation_summary(report: GenerationReport) -> str:
    metrics = report.metrics
    status = "PASSED" if report.passed else "FAILED"
    lines = [
        f"Generation evaluation: {status}",
        f"Dataset: {report.dataset_id} {report.dataset_version}",
        f"Generator: {report.generator_model}@{report.generator_model_revision}",
        f"Cases: {metrics.case_count}",
        f"Parse success: {metrics.parse_success_rate:.3f}",
        f"Expected fact coverage: {metrics.expected_fact_coverage:.3f}",
        f"Citation accuracy/coverage: {metrics.citation_accuracy:.3f}/{metrics.citation_coverage:.3f}",
        f"Faithfulness/hallucination: {metrics.answer_faithfulness:.3f}/{metrics.hallucination_rate:.3f}",
        f"Refusal accuracy: {metrics.refusal_accuracy:.3f}",
        f"Restricted fact leaks: {metrics.restricted_fact_leak_count}",
        f"TTFT mean/p95: {metrics.mean_time_to_first_token_ms:.1f}/{metrics.p95_time_to_first_token_ms:.1f} ms",
        f"End-to-end mean/p95: {metrics.mean_end_to_end_latency_ms:.1f}/{metrics.p95_end_to_end_latency_ms:.1f} ms",
        f"Generation throughput: {metrics.mean_tokens_per_second:.1f} tokens/s",
    ]
    lines.extend(f"Threshold failure: {failure}" for failure in report.threshold_failures)
    return "\n".join(lines)


def write_generation_report(report: GenerationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1000
