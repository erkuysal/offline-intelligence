from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evaluation.generation import GenerationReport


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactIdentity(StrictModel):
    model: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    format: Literal["gguf"]
    quantization: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    disk_size_bytes: int = Field(gt=0)
    adapter_id: str | None = None


class RuntimeIdentity(StrictModel):
    name: Literal["llama.cpp"]
    revision: str = Field(min_length=1)
    executable: str = Field(min_length=1)
    build: str = Field(min_length=1)
    context_size: int = Field(gt=0)
    parallelism: int = Field(gt=0)
    configured_gpu_layers: int = Field(ge=0)
    gpu_offload_observed: bool
    flash_attention: bool


class HardwareIdentity(StrictModel):
    hostname: str = Field(min_length=1)
    operating_system: str = Field(min_length=1)
    cpu: str = Field(min_length=1)
    system_ram_mib: float = Field(gt=0)
    gpu: str | None = None
    gpu_vram_mib: float | None = Field(default=None, gt=0)
    driver: str | None = None


class ResourceMetrics(StrictModel):
    peak_process_ram_mib: float = Field(ge=0)
    peak_gpu_vram_mib: float | None = Field(default=None, ge=0)
    gpu_memory_measurement: Literal[
        "per_process", "runtime_reported", "system_delta", "unavailable"
    ]


class PerformanceMetrics(StrictModel):
    cold_startup_ms: float = Field(ge=0)
    warmup_ms: float = Field(ge=0)
    sample_count: int = Field(gt=0)
    concurrency: int = Field(gt=0)
    mean_time_to_first_token_ms: float = Field(ge=0)
    p95_time_to_first_token_ms: float = Field(ge=0)
    mean_end_to_end_latency_ms: float = Field(ge=0)
    p95_end_to_end_latency_ms: float = Field(ge=0)
    mean_tokens_per_second: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_latency_order(self) -> PerformanceMetrics:
        if self.mean_end_to_end_latency_ms < self.mean_time_to_first_token_ms:
            raise ValueError("mean end-to-end latency cannot be lower than mean TTFT")
        if self.p95_end_to_end_latency_ms < self.p95_time_to_first_token_ms:
            raise ValueError("p95 end-to-end latency cannot be lower than p95 TTFT")
        return self


class InferenceMeasurement(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    report_type: Literal["inference_measurement"] = "inference_measurement"
    measured_at: datetime
    artifact: ArtifactIdentity
    runtime: RuntimeIdentity
    hardware: HardwareIdentity
    resources: ResourceMetrics
    performance: PerformanceMetrics


class BenchmarkThresholds(StrictModel):
    max_peak_process_ram_mib: float | None = Field(default=None, gt=0)
    max_peak_gpu_vram_mib: float | None = Field(default=None, gt=0)
    max_cold_startup_ms: float | None = Field(default=None, gt=0)
    max_mean_time_to_first_token_ms: float | None = Field(default=None, gt=0)
    max_p95_time_to_first_token_ms: float | None = Field(default=None, gt=0)
    max_mean_end_to_end_latency_ms: float | None = Field(default=None, gt=0)
    max_p95_end_to_end_latency_ms: float | None = Field(default=None, gt=0)
    min_mean_tokens_per_second: float | None = Field(default=None, gt=0)
    require_gpu_offload: bool = False
    require_quality_pass: bool = True


class BenchmarkContract(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    contract_type: Literal["inference_benchmark_contract"] = "inference_benchmark_contract"
    contract_id: str = Field(min_length=1)
    artifact: ArtifactIdentity
    runtime_name: Literal["llama.cpp"]
    runtime_revision: str = Field(min_length=1)
    thresholds: BenchmarkThresholds


class EvaluationEvidence(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    report_type: Literal["production_runtime_evaluation"]
    evaluation_mode: Literal["base", "base_rag", "adapter", "adapter_rag"]
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    corpus_version: str = Field(min_length=1)
    generator_model: str = Field(min_length=1)
    generator_model_revision: str = Field(min_length=1)
    content_policy: Literal["public", "restricted"]
    case_output_policy: Literal["reviewable", "redacted"]
    passed: bool
    threshold_failure_count: int = Field(ge=0)


class InferenceBenchmarkReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    report_type: Literal["inference_benchmark"] = "inference_benchmark"
    generated_at: datetime
    contract_id: str
    artifact: ArtifactIdentity
    runtime: RuntimeIdentity
    hardware: HardwareIdentity
    resources: ResourceMetrics
    performance: PerformanceMetrics
    thresholds: BenchmarkThresholds
    evaluation_evidence: EvaluationEvidence
    identity_failures: list[str]
    threshold_failures: list[str]

    @property
    def passed(self) -> bool:
        return not self.identity_failures and not self.threshold_failures


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_benchmark_contract(path: Path) -> BenchmarkContract:
    return BenchmarkContract.model_validate_json(path.read_text(encoding="utf-8"))


def load_inference_measurement(path: Path) -> InferenceMeasurement:
    return InferenceMeasurement.model_validate_json(path.read_text(encoding="utf-8"))


def load_generation_evidence(path: Path) -> GenerationReport:
    return GenerationReport.model_validate_json(path.read_text(encoding="utf-8"))


def build_inference_benchmark_report(
    contract: BenchmarkContract,
    measurement: InferenceMeasurement,
    quality_report: GenerationReport,
    *,
    quality_report_path: Path,
) -> InferenceBenchmarkReport:
    identity_failures = _identity_failures(contract, measurement, quality_report)
    threshold_failures = _threshold_failures(contract.thresholds, measurement, quality_report)
    evidence = EvaluationEvidence(
        path=str(quality_report_path),
        sha256=sha256_file(quality_report_path),
        report_type=quality_report.report_type,
        evaluation_mode=quality_report.evaluation_mode,
        dataset_id=quality_report.dataset_id,
        dataset_version=quality_report.dataset_version,
        corpus_version=quality_report.corpus_version,
        generator_model=quality_report.generator_model,
        generator_model_revision=quality_report.generator_model_revision,
        content_policy=quality_report.content_policy,
        case_output_policy=quality_report.case_output_policy,
        passed=quality_report.passed,
        threshold_failure_count=len(quality_report.threshold_failures),
    )
    return InferenceBenchmarkReport(
        generated_at=datetime.now(UTC),
        contract_id=contract.contract_id,
        artifact=measurement.artifact,
        runtime=measurement.runtime,
        hardware=measurement.hardware,
        resources=measurement.resources,
        performance=measurement.performance,
        thresholds=contract.thresholds,
        evaluation_evidence=evidence,
        identity_failures=identity_failures,
        threshold_failures=threshold_failures,
    )


def _identity_failures(
    contract: BenchmarkContract,
    measurement: InferenceMeasurement,
    quality_report: GenerationReport,
) -> list[str]:
    failures: list[str] = []
    expected_artifact = contract.artifact
    actual_artifact = measurement.artifact
    for field in (
        "model",
        "revision",
        "format",
        "quantization",
        "sha256",
        "disk_size_bytes",
        "adapter_id",
    ):
        expected = getattr(expected_artifact, field)
        actual = getattr(actual_artifact, field)
        if actual != expected:
            failures.append(f"artifact.{field}: expected {expected!r}, found {actual!r}")
    if measurement.runtime.name != contract.runtime_name:
        failures.append(
            f"runtime.name: expected {contract.runtime_name!r}, found {measurement.runtime.name!r}"
        )
    if measurement.runtime.revision != contract.runtime_revision:
        failures.append(
            "runtime.revision: expected "
            f"{contract.runtime_revision!r}, found {measurement.runtime.revision!r}"
        )
    if quality_report.generator_model != actual_artifact.model:
        failures.append("quality report generator_model does not match measured artifact")
    if quality_report.generator_model_revision != actual_artifact.revision:
        failures.append("quality report generator_model_revision does not match measured artifact")
    if quality_report.adapter_id != actual_artifact.adapter_id:
        failures.append("quality report adapter_id does not match measured artifact")
    return failures


def _threshold_failures(
    thresholds: BenchmarkThresholds,
    measurement: InferenceMeasurement,
    quality_report: GenerationReport,
) -> list[str]:
    resources = measurement.resources
    performance = measurement.performance
    failures: list[str] = []
    maximums = (
        ("peak process RAM", resources.peak_process_ram_mib, thresholds.max_peak_process_ram_mib),
        ("cold startup", performance.cold_startup_ms, thresholds.max_cold_startup_ms),
        (
            "mean TTFT",
            performance.mean_time_to_first_token_ms,
            thresholds.max_mean_time_to_first_token_ms,
        ),
        (
            "p95 TTFT",
            performance.p95_time_to_first_token_ms,
            thresholds.max_p95_time_to_first_token_ms,
        ),
        (
            "mean end-to-end latency",
            performance.mean_end_to_end_latency_ms,
            thresholds.max_mean_end_to_end_latency_ms,
        ),
        (
            "p95 end-to-end latency",
            performance.p95_end_to_end_latency_ms,
            thresholds.max_p95_end_to_end_latency_ms,
        ),
    )
    for label, actual, maximum in maximums:
        if maximum is not None and actual > maximum:
            failures.append(f"{label} {actual:.3f} exceeds maximum {maximum:.3f}")
    if (
        thresholds.max_peak_gpu_vram_mib is not None
        and resources.peak_gpu_vram_mib is not None
        and resources.peak_gpu_vram_mib > thresholds.max_peak_gpu_vram_mib
    ):
        failures.append(
            f"peak GPU VRAM {resources.peak_gpu_vram_mib:.3f} exceeds maximum "
            f"{thresholds.max_peak_gpu_vram_mib:.3f}"
        )
    minimum = thresholds.min_mean_tokens_per_second
    if minimum is not None and performance.mean_tokens_per_second < minimum:
        failures.append(
            f"mean throughput {performance.mean_tokens_per_second:.3f} is below minimum {minimum:.3f}"
        )
    if thresholds.require_quality_pass and not quality_report.passed:
        failures.append("protected quality evaluation did not pass")
    if thresholds.require_gpu_offload and not measurement.runtime.gpu_offload_observed:
        failures.append("required GPU offload was not observed")
    return failures


def format_inference_benchmark_summary(report: InferenceBenchmarkReport) -> str:
    status = "PASSED" if report.passed else "FAILED"
    lines = [
        f"Inference benchmark: {status}",
        f"Contract: {report.contract_id}",
        f"Artifact: {report.artifact.model}@{report.artifact.revision}",
        f"Quantization: {report.artifact.quantization}",
        f"Runtime: {report.runtime.name}@{report.runtime.revision}",
        f"Cold startup: {report.performance.cold_startup_ms:.1f} ms",
        "TTFT mean/p95: "
        f"{report.performance.mean_time_to_first_token_ms:.1f}/"
        f"{report.performance.p95_time_to_first_token_ms:.1f} ms",
        "End-to-end mean/p95: "
        f"{report.performance.mean_end_to_end_latency_ms:.1f}/"
        f"{report.performance.p95_end_to_end_latency_ms:.1f} ms",
        f"Throughput: {report.performance.mean_tokens_per_second:.1f} tokens/s",
    ]
    lines.extend(f"Identity failure: {failure}" for failure in report.identity_failures)
    lines.extend(f"Threshold failure: {failure}" for failure in report.threshold_failures)
    return "\n".join(lines)


def write_inference_benchmark_report(report: InferenceBenchmarkReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
