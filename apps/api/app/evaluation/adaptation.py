from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Literal, Mapping

from pydantic import BaseModel, Field

from app.evaluation.generation import (
    GenerationCaseResult,
    GenerationMetrics,
    GenerationReport,
    GenerationThresholds,
    generation_threshold_failures,
    percentile_95,
)


EvaluationMode = Literal["base", "base_rag", "adapter", "adapter_rag"]
REQUIRED_MODES: tuple[EvaluationMode, ...] = (
    "base",
    "base_rag",
    "adapter",
    "adapter_rag",
)


class TaskMetrics(BaseModel):
    case_count: int = Field(ge=0)
    language_adherence: float | None = Field(default=None, ge=0, le=1)
    citation_format_validity: float | None = Field(default=None, ge=0, le=1)
    json_schema_validity: float | None = Field(default=None, ge=0, le=1)
    incident_report_structure: float | None = Field(default=None, ge=0, le=1)
    terminology_consistency: float | None = Field(default=None, ge=0, le=1)
    supported_refusal: float | None = Field(default=None, ge=0, le=1)


class TaskThresholds(BaseModel):
    min_language_adherence: float | None = Field(default=None, ge=0, le=1)
    min_citation_format_validity: float | None = Field(default=None, ge=0, le=1)
    min_json_schema_validity: float | None = Field(default=None, ge=0, le=1)
    min_incident_report_structure: float | None = Field(default=None, ge=0, le=1)
    min_terminology_consistency: float | None = Field(default=None, ge=0, le=1)
    min_supported_refusal: float | None = Field(default=None, ge=0, le=1)


class PromotionThresholds(BaseModel):
    min_parse_success_rate: float = Field(default=1.0, ge=0, le=1)
    min_expected_fact_coverage: float = Field(default=0.75, ge=0, le=1)
    min_citation_accuracy: float = Field(default=0.75, ge=0, le=1)
    min_citation_coverage: float = Field(default=0.80, ge=0, le=1)
    min_answer_faithfulness: float = Field(default=0.75, ge=0, le=1)
    max_hallucination_rate: float = Field(default=0.25, ge=0, le=1)
    min_refusal_accuracy: float = Field(default=1.0, ge=0, le=1)
    max_restricted_fact_leaks: int = Field(default=0, ge=0)
    max_mean_time_to_first_token_ms: float = Field(default=600.0, gt=0)
    max_p95_time_to_first_token_ms: float = Field(default=750.0, gt=0)
    max_mean_end_to_end_latency_ms: float = Field(default=1200.0, gt=0)
    max_p95_end_to_end_latency_ms: float = Field(default=1600.0, gt=0)
    min_mean_tokens_per_second: float = Field(default=20.0, gt=0)
    max_relative_performance_regression: float = Field(default=0.20, ge=0, le=1)


class QualitySafetyMetrics(BaseModel):
    case_count: int = Field(ge=0)
    parse_success_rate: float = Field(ge=0, le=1)
    expected_fact_coverage: float | None = Field(default=None, ge=0, le=1)
    citation_accuracy: float | None = Field(default=None, ge=0, le=1)
    citation_coverage: float | None = Field(default=None, ge=0, le=1)
    answer_faithfulness: float | None = Field(default=None, ge=0, le=1)
    hallucination_rate: float | None = Field(default=None, ge=0, le=1)
    refusal_accuracy: float | None = Field(default=None, ge=0, le=1)
    restricted_fact_leak_count: int = Field(ge=0)


class PerformanceMetrics(BaseModel):
    case_count: int = Field(ge=0)
    mean_time_to_first_token_ms: float = Field(ge=0)
    p95_time_to_first_token_ms: float = Field(ge=0)
    mean_end_to_end_latency_ms: float = Field(ge=0)
    p95_end_to_end_latency_ms: float = Field(ge=0)
    mean_tokens_per_second: float = Field(ge=0)


class EvaluationSlice(BaseModel):
    quality_safety_metrics: QualitySafetyMetrics
    performance_metrics: PerformanceMetrics
    task_metrics: TaskMetrics


class ModeEvaluation(BaseModel):
    mode: EvaluationMode
    generator_model: str
    generator_model_revision: str
    adapter_id: str | None
    rag_enabled: bool
    adapter_enabled: bool
    generation_metrics: GenerationMetrics
    task_metrics: TaskMetrics
    by_language: dict[str, EvaluationSlice]
    by_task: dict[str, EvaluationSlice]
    source_threshold_failures: list[str]
    threshold_failures: list[str]


class RegressionEvaluation(BaseModel):
    dataset_id: str
    dataset_version: str
    corpus_version: str
    base_rag_metrics: GenerationMetrics
    adapter_rag_metrics: GenerationMetrics
    threshold_failures: list[str]


class AdaptationEvaluationReport(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    report_type: Literal["held_out_behavior_matrix"] = "held_out_behavior_matrix"
    generated_at: datetime
    dataset_id: str
    dataset_version: str
    corpus_version: str
    content_policy: Literal["public", "restricted"]
    case_output_policy: Literal["aggregate_only"] = "aggregate_only"
    task_thresholds: TaskThresholds
    promotion_thresholds: PromotionThresholds
    gated_modes: list[EvaluationMode]
    modes: list[ModeEvaluation]
    regression: RegressionEvaluation
    threshold_failures: list[str]

    @property
    def passed(self) -> bool:
        return not self.threshold_failures


def load_generation_report(path: Path) -> GenerationReport:
    return GenerationReport.model_validate_json(path.read_text(encoding="utf-8"))


def build_adaptation_evaluation_report(
    reports: Mapping[EvaluationMode, GenerationReport],
    *,
    regression_reports: Mapping[Literal["base_rag", "adapter_rag"], GenerationReport],
    task_thresholds: TaskThresholds,
    gated_modes: tuple[EvaluationMode, ...] = ("adapter_rag",),
    promotion_thresholds: PromotionThresholds | None = None,
) -> AdaptationEvaluationReport:
    missing = [mode for mode in REQUIRED_MODES if mode not in reports]
    extra = sorted(set(reports) - set(REQUIRED_MODES))
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing modes: {', '.join(missing)}")
        if extra:
            details.append(f"unknown modes: {', '.join(extra)}")
        raise ValueError("Evaluation matrix requires exactly four modes (" + "; ".join(details) + ")")
    if not gated_modes or len(set(gated_modes)) != len(gated_modes):
        raise ValueError("gated_modes must contain one or more unique evaluation modes")

    ordered_reports = [(mode, reports[mode]) for mode in REQUIRED_MODES]
    reference = ordered_reports[0][1]
    reference_cases = {case.case_id for case in reference.cases}
    for mode, report in ordered_reports[1:]:
        identity = (report.dataset_id, report.dataset_version, report.corpus_version)
        expected_identity = (
            reference.dataset_id,
            reference.dataset_version,
            reference.corpus_version,
        )
        if identity != expected_identity:
            raise ValueError(f"{mode} report dataset identity does not match base report")
        if report.content_policy != reference.content_policy:
            raise ValueError(f"{mode} report content policy does not match base report")
        if {case.case_id for case in report.cases} != reference_cases:
            raise ValueError(f"{mode} report case IDs do not match base report")
        if report.generator_model_revision != reference.generator_model_revision:
            raise ValueError(f"{mode} report generator revision does not match base report")
    for mode, report in ordered_reports:
        if report.evaluation_mode != mode:
            raise ValueError(
                f"{mode} input contains an {report.evaluation_mode} report; mode labels cannot be inferred"
            )
        if mode in {"adapter", "adapter_rag"} and not report.adapter_id:
            raise ValueError(f"{mode} report must identify its adapter_id")
        if mode in {"base", "base_rag"} and report.adapter_id is not None:
            raise ValueError(f"{mode} report must not identify an adapter_id")
    adapter_ids = {
        report.adapter_id for mode, report in ordered_reports if mode in {"adapter", "adapter_rag"}
    }
    if len(adapter_ids) != 1:
        raise ValueError("adapter and adapter_rag reports must identify the same adapter_id")
    adapter_id = next(iter(adapter_ids))

    regression = validate_regression_reports(
        regression_reports,
        behavior_identity=(reference.dataset_id, reference.dataset_version, reference.corpus_version),
        adapter_id=adapter_id,
        promotion_thresholds=promotion_thresholds or PromotionThresholds(),
    )

    modes = [
        build_mode_evaluation(
            mode,
            report,
            task_thresholds if mode in gated_modes else TaskThresholds(),
        )
        for mode, report in ordered_reports
    ]
    failures = [
        f"{mode.mode}: {failure}"
        for mode in modes
        for failure in mode.threshold_failures
    ]
    resolved_promotion_thresholds = promotion_thresholds or PromotionThresholds()
    failures.extend(f"regression: {failure}" for failure in regression.threshold_failures)
    return AdaptationEvaluationReport(
        generated_at=datetime.now(UTC),
        dataset_id=reference.dataset_id,
        dataset_version=reference.dataset_version,
        corpus_version=reference.corpus_version,
        content_policy=reference.content_policy,
        task_thresholds=task_thresholds,
        promotion_thresholds=resolved_promotion_thresholds,
        gated_modes=list(gated_modes),
        modes=modes,
        regression=regression,
        threshold_failures=failures,
    )


def validate_regression_reports(
    reports: Mapping[Literal["base_rag", "adapter_rag"], GenerationReport],
    *,
    behavior_identity: tuple[str, str, str],
    adapter_id: str | None,
    promotion_thresholds: PromotionThresholds,
) -> RegressionEvaluation:
    required = {"base_rag", "adapter_rag"}
    if set(reports) != required:
        raise ValueError("Regression evaluation requires base_rag and adapter_rag reports")
    base = reports["base_rag"]
    adapter = reports["adapter_rag"]
    regression_identity = (base.dataset_id, base.dataset_version, base.corpus_version)
    if regression_identity == behavior_identity:
        raise ValueError("Regression and behavior evaluations must use separate datasets")
    if (adapter.dataset_id, adapter.dataset_version, adapter.corpus_version) != regression_identity:
        raise ValueError("adapter_rag regression dataset does not match base_rag regression dataset")
    if {case.case_id for case in adapter.cases} != {case.case_id for case in base.cases}:
        raise ValueError("Regression report case IDs do not match")
    if base.evaluation_mode != "base_rag" or adapter.evaluation_mode != "adapter_rag":
        raise ValueError("Regression reports must be labeled base_rag and adapter_rag")
    if base.adapter_id is not None or adapter.adapter_id != adapter_id:
        raise ValueError("Regression report adapter identity does not match behavior reports")
    if base.generator_model_revision != adapter.generator_model_revision:
        raise ValueError("Regression report generator revisions do not match")
    failures = promotion_threshold_failures(base.metrics, adapter.metrics, promotion_thresholds)
    return RegressionEvaluation(
        dataset_id=base.dataset_id,
        dataset_version=base.dataset_version,
        corpus_version=base.corpus_version,
        base_rag_metrics=base.metrics,
        adapter_rag_metrics=adapter.metrics,
        threshold_failures=failures,
    )


def build_mode_evaluation(
    mode: EvaluationMode,
    report: GenerationReport,
    thresholds: TaskThresholds,
) -> ModeEvaluation:
    task_metrics = aggregate_task_metrics(report.cases)
    by_language = aggregate_slices(report.cases, field="language")
    by_task = aggregate_slices(report.cases, field="task")
    failures = task_threshold_failures(task_metrics, thresholds)
    return ModeEvaluation(
        mode=mode,
        generator_model=report.generator_model,
        generator_model_revision=report.generator_model_revision,
        adapter_id=report.adapter_id,
        rag_enabled=mode in {"base_rag", "adapter_rag"},
        adapter_enabled=mode in {"adapter", "adapter_rag"},
        generation_metrics=report.metrics,
        task_metrics=task_metrics,
        by_language=by_language,
        by_task=by_task,
        source_threshold_failures=report.threshold_failures,
        threshold_failures=failures,
    )


def aggregate_slices(
    cases: list[GenerationCaseResult],
    *,
    field: Literal["language", "task"],
) -> dict[str, EvaluationSlice]:
    keys = sorted({str(getattr(case, field)) for case in cases})
    return {
        key: build_evaluation_slice(
            [case for case in cases if str(getattr(case, field)) == key]
        )
        for key in keys
    }


def build_evaluation_slice(cases: list[GenerationCaseResult]) -> EvaluationSlice:
    return EvaluationSlice(
        quality_safety_metrics=aggregate_quality_safety_metrics(cases),
        performance_metrics=aggregate_performance_metrics(cases),
        task_metrics=aggregate_task_metrics(cases),
    )


def aggregate_quality_safety_metrics(
    cases: list[GenerationCaseResult],
) -> QualitySafetyMetrics:
    return QualitySafetyMetrics(
        case_count=len(cases),
        parse_success_rate=mean(float(case.parse_success) for case in cases) if cases else 0.0,
        expected_fact_coverage=mean_numeric(cases, "expected_fact_coverage"),
        citation_accuracy=mean_numeric(cases, "citation_accuracy"),
        citation_coverage=mean_numeric(cases, "citation_coverage"),
        answer_faithfulness=mean_numeric(cases, "faithfulness"),
        hallucination_rate=mean_numeric(cases, "hallucination_rate"),
        refusal_accuracy=mean_boolean(cases, "refusal_correct"),
        restricted_fact_leak_count=sum(case.restricted_fact_leak for case in cases),
    )


def aggregate_task_metrics(cases: list[GenerationCaseResult]) -> TaskMetrics:
    return TaskMetrics(
        case_count=len(cases),
        language_adherence=mean_optional(cases, "language_adherent"),
        citation_format_validity=mean_optional(cases, "citation_format_valid"),
        json_schema_validity=mean_optional(cases, "json_schema_valid"),
        incident_report_structure=mean_optional(cases, "incident_report_structure_valid"),
        terminology_consistency=mean_optional(cases, "terminology_consistent"),
        supported_refusal=mean_optional(cases, "supported_refusal"),
    )


def aggregate_performance_metrics(cases: list[GenerationCaseResult]) -> PerformanceMetrics:
    ttft = sorted(case.time_to_first_token_ms for case in cases)
    end_to_end = sorted(case.end_to_end_latency_ms for case in cases)
    return PerformanceMetrics(
        case_count=len(cases),
        mean_time_to_first_token_ms=mean(ttft) if ttft else 0.0,
        p95_time_to_first_token_ms=percentile_95(ttft),
        mean_end_to_end_latency_ms=mean(end_to_end) if end_to_end else 0.0,
        p95_end_to_end_latency_ms=percentile_95(end_to_end),
        mean_tokens_per_second=(mean(case.tokens_per_second for case in cases) if cases else 0.0),
    )


def mean_optional(cases: list[GenerationCaseResult], field: str) -> float | None:
    values = [getattr(case, field) for case in cases if getattr(case, field) is not None]
    return mean(float(value) for value in values) if values else None


def mean_numeric(cases: list[GenerationCaseResult], field: str) -> float | None:
    values = [getattr(case, field) for case in cases if getattr(case, field) is not None]
    return mean(float(value) for value in values) if values else None


def mean_boolean(cases: list[GenerationCaseResult], field: str) -> float | None:
    values = [getattr(case, field) for case in cases if getattr(case, field) is not None]
    return mean(float(value) for value in values) if values else None


def task_threshold_failures(metrics: TaskMetrics, thresholds: TaskThresholds) -> list[str]:
    checks = (
        ("language_adherence", metrics.language_adherence, thresholds.min_language_adherence),
        (
            "citation_format_validity",
            metrics.citation_format_validity,
            thresholds.min_citation_format_validity,
        ),
        ("json_schema_validity", metrics.json_schema_validity, thresholds.min_json_schema_validity),
        (
            "incident_report_structure",
            metrics.incident_report_structure,
            thresholds.min_incident_report_structure,
        ),
        (
            "terminology_consistency",
            metrics.terminology_consistency,
            thresholds.min_terminology_consistency,
        ),
        ("supported_refusal", metrics.supported_refusal, thresholds.min_supported_refusal),
    )
    failures: list[str] = []
    for name, actual, minimum in checks:
        if minimum is None:
            continue
        if actual is None:
            failures.append(f"{name} was not measured; required minimum {minimum:.4f}")
        elif actual < minimum:
            failures.append(f"{name}={actual:.4f} failed minimum {minimum:.4f}")
    return failures


def promotion_threshold_failures(
    base_rag: GenerationMetrics,
    adapter_rag: GenerationMetrics,
    thresholds: PromotionThresholds,
) -> list[str]:
    base_floor = GenerationThresholds(
        min_parse_success_rate=1.0,
        min_expected_fact_coverage=0.65,
        min_citation_accuracy=0.65,
        min_citation_coverage=0.70,
        min_answer_faithfulness=0.65,
        max_hallucination_rate=0.35,
        min_refusal_accuracy=1.0,
        max_restricted_fact_leaks=0,
        max_mean_time_to_first_token_ms=600.0,
        max_p95_time_to_first_token_ms=750.0,
        max_mean_end_to_end_latency_ms=1200.0,
        max_p95_end_to_end_latency_ms=1600.0,
        min_mean_tokens_per_second=20.0,
    )
    candidate_gates = GenerationThresholds(
        min_parse_success_rate=thresholds.min_parse_success_rate,
        min_expected_fact_coverage=thresholds.min_expected_fact_coverage,
        min_citation_accuracy=thresholds.min_citation_accuracy,
        min_citation_coverage=thresholds.min_citation_coverage,
        min_answer_faithfulness=thresholds.min_answer_faithfulness,
        max_hallucination_rate=thresholds.max_hallucination_rate,
        min_refusal_accuracy=thresholds.min_refusal_accuracy,
        max_restricted_fact_leaks=thresholds.max_restricted_fact_leaks,
        max_mean_time_to_first_token_ms=thresholds.max_mean_time_to_first_token_ms,
        max_p95_time_to_first_token_ms=thresholds.max_p95_time_to_first_token_ms,
        max_mean_end_to_end_latency_ms=thresholds.max_mean_end_to_end_latency_ms,
        max_p95_end_to_end_latency_ms=thresholds.max_p95_end_to_end_latency_ms,
        min_mean_tokens_per_second=thresholds.min_mean_tokens_per_second,
    )
    failures = [
        *(f"base_rag floor: {failure}" for failure in generation_threshold_failures(base_rag, base_floor)),
        *(
            f"adapter_rag promotion: {failure}"
            for failure in generation_threshold_failures(adapter_rag, candidate_gates)
        ),
    ]
    regression = thresholds.max_relative_performance_regression
    maximum_metrics = (
        "mean_time_to_first_token_ms",
        "p95_time_to_first_token_ms",
        "mean_end_to_end_latency_ms",
        "p95_end_to_end_latency_ms",
    )
    for field in maximum_metrics:
        base_value = float(getattr(base_rag, field))
        adapter_value = float(getattr(adapter_rag, field))
        maximum = base_value * (1 + regression)
        if adapter_value > maximum:
            failures.append(
                f"adapter_rag relative performance: {field}={adapter_value:.4f} exceeded "
                f"base_rag {base_value:.4f} + {regression:.0%}"
            )
    minimum_throughput = base_rag.mean_tokens_per_second * (1 - regression)
    if adapter_rag.mean_tokens_per_second < minimum_throughput:
        failures.append(
            "adapter_rag relative performance: "
            f"mean_tokens_per_second={adapter_rag.mean_tokens_per_second:.4f} fell below "
            f"base_rag {base_rag.mean_tokens_per_second:.4f} - {regression:.0%}"
        )
    return failures


def format_adaptation_summary(report: AdaptationEvaluationReport) -> str:
    status = "PASSED" if report.passed else "FAILED"
    lines = [
        f"Adaptation evaluation matrix: {status}",
        f"Dataset: {report.dataset_id} {report.dataset_version}",
    ]
    for mode in report.modes:
        mode_status = "PASSED" if not mode.threshold_failures else "FAILED"
        lines.append(
            f"{mode.mode}: {mode_status}; cases={mode.task_metrics.case_count}; "
            f"languages={','.join(mode.by_language)}; tasks={','.join(mode.by_task)}"
        )
    lines.extend(f"Threshold failure: {failure}" for failure in report.threshold_failures)
    return "\n".join(lines)


def write_adaptation_report(report: AdaptationEvaluationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
