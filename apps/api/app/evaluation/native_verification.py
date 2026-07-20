from __future__ import annotations

from array import array
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import mean, median
from time import perf_counter
from typing import Callable, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.evaluation.native_profile import ProfileWorkload, deterministic_inputs
from app.native.vector_similarity import (
    NativeCapabilities,
    cosine_batch,
    cosine_batch_fallback,
    invoke_native_cosine_batch_buffers,
    load_native_library,
    native_capabilities,
    prepare_contiguous_batch,
)


class NativeVerificationContract(BaseModel):
    contract_type: Literal["native_vector_verification_contract"] = (
        "native_vector_verification_contract"
    )
    schema_version: Literal["1.0"] = "1.0"
    candidate_id: Literal["batch_cosine_f32"] = "batch_cosine_f32"
    fuzz_seed: int = Field(ge=0)
    fuzz_cases: int = Field(ge=1, le=10000)
    fuzz_max_dimensions: int = Field(ge=1, le=16384)
    fuzz_max_batch_size: int = Field(ge=1, le=10000)
    absolute_tolerance: float = Field(gt=0, le=1)
    relative_tolerance: float = Field(gt=0, le=1)
    relative_epsilon: float = Field(gt=0, le=1)
    warmup_samples: int = Field(default=2, ge=0, le=100)
    measured_samples: int = Field(default=7, ge=3, le=100)
    performance_workloads: list[ProfileWorkload] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_workloads(self) -> Self:
        identities = {
            (item.dimensions, item.batch_size) for item in self.performance_workloads
        }
        if len(identities) != len(self.performance_workloads):
            raise ValueError("verification workloads must be unique by dimensions and batch_size")
        return self


class NumericalVerification(BaseModel):
    seed: int
    case_count: int
    value_count: int
    failure_count: int
    maximum_absolute_error: float
    maximum_relative_error: float
    absolute_tolerance: float
    relative_tolerance: float
    passed: bool


class BoundaryBenchmark(BaseModel):
    dimensions: int
    batch_size: int
    calls_per_sample: int
    measured_samples: int
    fallback_mean_ms: float
    fallback_p50_ms: float
    fallback_p95_ms: float
    conversion_mean_ms: float
    conversion_p50_ms: float
    kernel_mean_ms: float
    kernel_p50_ms: float
    kernel_p95_ms: float
    kernel_speedup: float
    boundary_mean_ms: float
    boundary_p50_ms: float
    boundary_p95_ms: float
    boundary_inclusive_speedup: float
    boundary_vectors_per_second: float
    checksum_difference: float


class NativeVerificationReport(BaseModel):
    report_type: Literal["native_vector_verification"] = "native_vector_verification"
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    candidate_id: str
    library_sha256: str
    capabilities: NativeCapabilities
    numerical: NumericalVerification
    benchmarks: list[BoundaryBenchmark]
    performance_gate_applied: bool = False

    @property
    def passed(self) -> bool:
        return self.capabilities.backend == "native" and self.numerical.passed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def float32_values(values: list[float]) -> list[float]:
    return array("f", values).tolist()


def verify_numerical_equivalence(
    contract: NativeVerificationContract,
    library_path: Path,
) -> NumericalVerification:
    generator = random.Random(contract.fuzz_seed)
    maximum_absolute_error = 0.0
    maximum_relative_error = 0.0
    failure_count = 0
    value_count = 0

    for _ in range(contract.fuzz_cases):
        dimensions = generator.randint(1, contract.fuzz_max_dimensions)
        batch_size = generator.randint(1, contract.fuzz_max_batch_size)
        query = float32_values(
            [generator.uniform(-1.0, 1.0) for _ in range(dimensions)]
        )
        rows = [
            float32_values(
                [generator.uniform(-1.0, 1.0) for _ in range(dimensions)]
            )
            for _ in range(batch_size)
        ]
        reference = cosine_batch_fallback(query, rows)
        native = cosine_batch(query, rows, library_path=library_path)
        for expected, actual in zip(reference, native, strict=True):
            absolute_error = abs(actual - expected)
            relative_error = absolute_error / max(
                abs(expected), contract.relative_epsilon
            )
            maximum_absolute_error = max(maximum_absolute_error, absolute_error)
            maximum_relative_error = max(maximum_relative_error, relative_error)
            if absolute_error > (
                contract.absolute_tolerance
                + contract.relative_tolerance * abs(expected)
            ):
                failure_count += 1
            value_count += 1

    return NumericalVerification(
        seed=contract.fuzz_seed,
        case_count=contract.fuzz_cases,
        value_count=value_count,
        failure_count=failure_count,
        maximum_absolute_error=maximum_absolute_error,
        maximum_relative_error=maximum_relative_error,
        absolute_tolerance=contract.absolute_tolerance,
        relative_tolerance=contract.relative_tolerance,
        passed=failure_count == 0,
    )


def percentile_nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def measure_operation(
    operation: Callable[[], list[float]],
    *,
    warmup_samples: int,
    measured_samples: int,
    calls_per_sample: int,
) -> tuple[list[float], float]:
    for _ in range(warmup_samples):
        operation()
    observations_ms: list[float] = []
    checksum = 0.0
    for _ in range(measured_samples):
        started_at = perf_counter()
        for _ in range(calls_per_sample):
            checksum += sum(operation())
        observations_ms.append(
            (perf_counter() - started_at) * 1000 / calls_per_sample
        )
    return observations_ms, checksum


def benchmark_boundary(
    contract: NativeVerificationContract,
    workload: ProfileWorkload,
    library_path: Path,
) -> BoundaryBenchmark:
    query, rows = deterministic_inputs(workload.dimensions, workload.batch_size)
    fallback_observations, fallback_checksum = measure_operation(
        lambda: cosine_batch_fallback(query, rows),
        warmup_samples=contract.warmup_samples,
        measured_samples=contract.measured_samples,
        calls_per_sample=workload.calls_per_sample,
    )
    conversion_observations: list[float] = []
    for _ in range(contract.warmup_samples):
        prepare_contiguous_batch(query, rows)
    for _ in range(contract.measured_samples):
        started_at = perf_counter()
        for _ in range(workload.calls_per_sample):
            prepare_contiguous_batch(query, rows)
        conversion_observations.append(
            (perf_counter() - started_at) * 1000 / workload.calls_per_sample
        )

    query_buffer, rows_buffer = prepare_contiguous_batch(query, rows)
    library = load_native_library(library_path.expanduser().absolute())
    kernel_observations, kernel_checksum = measure_operation(
        lambda: invoke_native_cosine_batch_buffers(
            library,
            query_buffer,
            rows_buffer,
            row_count=workload.batch_size,
        ),
        warmup_samples=contract.warmup_samples,
        measured_samples=contract.measured_samples,
        calls_per_sample=workload.calls_per_sample,
    )
    boundary_observations, boundary_checksum = measure_operation(
        lambda: cosine_batch(query, rows, library_path=library_path),
        warmup_samples=contract.warmup_samples,
        measured_samples=contract.measured_samples,
        calls_per_sample=workload.calls_per_sample,
    )
    fallback_mean = mean(fallback_observations)
    conversion_mean = mean(conversion_observations)
    kernel_mean = mean(kernel_observations)
    boundary_mean = mean(boundary_observations)
    return BoundaryBenchmark(
        dimensions=workload.dimensions,
        batch_size=workload.batch_size,
        calls_per_sample=workload.calls_per_sample,
        measured_samples=contract.measured_samples,
        fallback_mean_ms=round(fallback_mean, 6),
        fallback_p50_ms=round(median(fallback_observations), 6),
        fallback_p95_ms=round(
            percentile_nearest_rank(fallback_observations, 0.95), 6
        ),
        conversion_mean_ms=round(conversion_mean, 6),
        conversion_p50_ms=round(median(conversion_observations), 6),
        kernel_mean_ms=round(kernel_mean, 6),
        kernel_p50_ms=round(median(kernel_observations), 6),
        kernel_p95_ms=round(
            percentile_nearest_rank(kernel_observations, 0.95), 6
        ),
        kernel_speedup=round(fallback_mean / kernel_mean, 6),
        boundary_mean_ms=round(boundary_mean, 6),
        boundary_p50_ms=round(median(boundary_observations), 6),
        boundary_p95_ms=round(
            percentile_nearest_rank(boundary_observations, 0.95), 6
        ),
        boundary_inclusive_speedup=round(fallback_mean / boundary_mean, 6),
        boundary_vectors_per_second=round(
            workload.batch_size / (boundary_mean / 1000), 3
        ),
        checksum_difference=max(
            abs(fallback_checksum - kernel_checksum),
            abs(fallback_checksum - boundary_checksum),
        ),
    )


def build_native_verification_report(
    contract: NativeVerificationContract,
    library_path: Path,
) -> NativeVerificationReport:
    library_path = library_path.expanduser().absolute()
    capabilities = native_capabilities(library_path)
    if capabilities.backend != "native":
        raise ValueError(
            f"native verification requires a compatible library: {capabilities.fallback_reason}"
        )
    return NativeVerificationReport(
        generated_at=datetime.now(UTC),
        candidate_id=contract.candidate_id,
        library_sha256=sha256_file(library_path),
        capabilities=capabilities,
        numerical=verify_numerical_equivalence(contract, library_path),
        benchmarks=[
            benchmark_boundary(contract, workload, library_path)
            for workload in contract.performance_workloads
        ],
    )


def load_native_verification_contract(path: Path) -> NativeVerificationContract:
    return NativeVerificationContract.model_validate_json(path.read_text(encoding="utf-8"))


def write_native_verification_report(
    report: NativeVerificationReport,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json") | {"passed": report.passed}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def format_native_verification_summary(report: NativeVerificationReport) -> str:
    lines = [
        f"Native vector verification: {'PASS' if report.passed else 'FAIL'}",
        f"Fuzz cases: {report.numerical.case_count}",
        f"Values compared: {report.numerical.value_count}",
        f"Maximum absolute error: {report.numerical.maximum_absolute_error:.3e}",
    ]
    lines.extend(
        f"- D={item.dimensions}, N={item.batch_size}: "
        f"kernel p50={item.kernel_p50_ms:.3f} ms, "
        f"boundary p50={item.boundary_p50_ms:.3f} ms, "
        f"boundary speedup={item.boundary_inclusive_speedup:.2f}x"
        for item in report.benchmarks
    )
    return "\n".join(lines)
