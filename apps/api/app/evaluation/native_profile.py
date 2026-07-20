from __future__ import annotations

from datetime import UTC, datetime
import math
import os
from pathlib import Path
import platform
from statistics import mean, median
from time import perf_counter
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.native.vector_similarity import cosine_batch_fallback


class ProfileWorkload(BaseModel):
    dimensions: int = Field(gt=0, le=16384)
    batch_size: int = Field(gt=0, le=100000)
    calls_per_sample: int = Field(default=1, gt=0, le=10000)


class NativeProfileContract(BaseModel):
    contract_type: Literal["native_vector_profile_contract"] = "native_vector_profile_contract"
    schema_version: Literal["1.0"] = "1.0"
    candidate_id: Literal["batch_cosine_f32"] = "batch_cosine_f32"
    use_case: Literal["offline_evaluation_and_experimental_reranking"] = (
        "offline_evaluation_and_experimental_reranking"
    )
    warmup_samples: int = Field(default=2, ge=0, le=100)
    measured_samples: int = Field(default=7, ge=3, le=100)
    workloads: list[ProfileWorkload] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_workloads(self) -> Self:
        identities = {(item.dimensions, item.batch_size) for item in self.workloads}
        if len(identities) != len(self.workloads):
            raise ValueError("native profile workloads must be unique by dimensions and batch_size")
        return self


class HostIdentity(BaseModel):
    operating_system: str
    machine: str
    processor: str
    python: str
    cpu_count: int


class BaselineMeasurement(BaseModel):
    implementation: Literal["python_scalar"] = "python_scalar"
    dimensions: int
    batch_size: int
    calls_per_sample: int
    measured_samples: int
    input_bytes_per_call: int
    mean_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    mean_vectors_per_second: float
    checksum: float


class NativeProfileReport(BaseModel):
    report_type: Literal["native_vector_profile"] = "native_vector_profile"
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    candidate_id: str
    use_case: str
    production_dense_retrieval_owner: Literal["postgresql_pgvector"] = "postgresql_pgvector"
    production_path_selected: bool = False
    decision: Literal["proceed_experimental_only"] = "proceed_experimental_only"
    decision_reason: str
    host: HostIdentity
    measurements: list[BaselineMeasurement]


def deterministic_inputs(dimensions: int, batch_size: int) -> tuple[list[float], list[list[float]]]:
    query = [(((index * 17) % 101) - 50) / 50 for index in range(dimensions)]
    rows = [
        [(((row_index * 13 + index * 7) % 97) - 48) / 48 for index in range(dimensions)]
        for row_index in range(batch_size)
    ]
    return query, rows


def percentile_nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires observations")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def measure_python_baseline(
    workload: ProfileWorkload,
    *,
    warmup_samples: int,
    measured_samples: int,
) -> BaselineMeasurement:
    query, rows = deterministic_inputs(workload.dimensions, workload.batch_size)
    for _ in range(warmup_samples):
        cosine_batch_fallback(query, rows)

    observations_ms: list[float] = []
    checksum = 0.0
    for _ in range(measured_samples):
        started_at = perf_counter()
        for _ in range(workload.calls_per_sample):
            scores = cosine_batch_fallback(query, rows)
            checksum += sum(scores)
        duration_ms = (perf_counter() - started_at) * 1000 / workload.calls_per_sample
        observations_ms.append(duration_ms)

    mean_latency_ms = mean(observations_ms)
    return BaselineMeasurement(
        dimensions=workload.dimensions,
        batch_size=workload.batch_size,
        calls_per_sample=workload.calls_per_sample,
        measured_samples=measured_samples,
        input_bytes_per_call=(workload.batch_size + 1) * workload.dimensions * 4,
        mean_latency_ms=round(mean_latency_ms, 6),
        p50_latency_ms=round(median(observations_ms), 6),
        p95_latency_ms=round(percentile_nearest_rank(observations_ms, 0.95), 6),
        mean_vectors_per_second=round(workload.batch_size / (mean_latency_ms / 1000), 3),
        checksum=round(checksum, 9),
    )


def cpu_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except (OSError, IndexError):
        pass
    return platform.processor() or "unknown"


def build_native_profile_report(contract: NativeProfileContract) -> NativeProfileReport:
    return NativeProfileReport(
        generated_at=datetime.now(UTC),
        candidate_id=contract.candidate_id,
        use_case=contract.use_case,
        decision_reason=(
            "Production dense retrieval already uses PostgreSQL/pgvector. Continue only as a "
            "fallback-backed batch primitive for offline evaluation and experimental reranking "
            "until an end-to-end benchmark demonstrates material value."
        ),
        host=HostIdentity(
            operating_system=platform.platform(),
            machine=platform.machine(),
            processor=cpu_name(),
            python=platform.python_version(),
            cpu_count=os.cpu_count() or 0,
        ),
        measurements=[
            measure_python_baseline(
                workload,
                warmup_samples=contract.warmup_samples,
                measured_samples=contract.measured_samples,
            )
            for workload in contract.workloads
        ],
    )


def load_native_profile_contract(path: Path) -> NativeProfileContract:
    return NativeProfileContract.model_validate_json(path.read_text(encoding="utf-8"))


def write_native_profile_report(report: NativeProfileReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


def format_native_profile_summary(report: NativeProfileReport) -> str:
    lines = [
        "Native candidate profile: BASELINE RECORDED",
        f"Candidate: {report.candidate_id}",
        f"Decision: {report.decision}",
    ]
    lines.extend(
        f"- D={item.dimensions}, N={item.batch_size}: "
        f"p50={item.p50_latency_ms:.3f} ms, "
        f"p95={item.p95_latency_ms:.3f} ms, "
        f"throughput={item.mean_vectors_per_second:.1f} vectors/s"
        for item in report.measurements
    )
    return "\n".join(lines)
