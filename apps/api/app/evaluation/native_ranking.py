from __future__ import annotations

from array import array
from datetime import UTC, datetime
import json
import math
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Callable, Literal

from pydantic import BaseModel, Field

from app.native.vector_similarity import (
    cosine_batch_contiguous,
    cosine_batch_contiguous_fallback,
    native_capabilities,
)


class NativeRankingContract(BaseModel):
    contract_type: Literal["native_contiguous_ranking_contract"] = (
        "native_contiguous_ranking_contract"
    )
    schema_version: Literal["1.0"] = "1.0"
    dimensions: int = Field(gt=0, le=16384)
    row_count: int = Field(gt=0, le=100000)
    top_k: int = Field(gt=0, le=1000)
    warmup_samples: int = Field(default=2, ge=0, le=100)
    measured_samples: int = Field(default=7, ge=3, le=100)
    minimum_speedup: float = Field(gt=1)
    maximum_score_error: float = Field(gt=0, le=1)


class RankingTiming(BaseModel):
    mean_ms: float
    p50_ms: float
    p95_ms: float


class NativeRankingReport(BaseModel):
    report_type: Literal["native_contiguous_ranking"] = "native_contiguous_ranking"
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    dimensions: int
    row_count: int
    top_k: int
    input_bytes: int
    preparation_in_timing: bool = False
    fallback: RankingTiming
    native: RankingTiming
    speedup: float
    top_k_identity_match: bool
    maximum_top_k_score_error: float
    threshold_failures: list[str]
    native_build_info: str

    @property
    def passed(self) -> bool:
        return not self.threshold_failures


def deterministic_contiguous_inputs(
    dimensions: int,
    row_count: int,
) -> tuple[array[float], array[float]]:
    query = array(
        "f", ((((index * 17) % 101) - 50) / 50 for index in range(dimensions))
    )
    rows = array(
        "f",
        (
            (((row_index * 13 + dimension_index * 7) % 97) - 48) / 48
            for row_index in range(row_count)
            for dimension_index in range(dimensions)
        ),
    )
    return query, rows


def percentile_nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def rank_scores(scores: list[float], top_k: int) -> list[tuple[int, float]]:
    indices = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)[:top_k]
    return [(index, scores[index]) for index in indices]


def measure_ranking(
    operation: Callable[[], list[float]],
    *,
    top_k: int,
    warmup_samples: int,
    measured_samples: int,
) -> tuple[RankingTiming, list[tuple[int, float]]]:
    for _ in range(warmup_samples):
        rank_scores(operation(), top_k)
    observations: list[float] = []
    result: list[tuple[int, float]] = []
    for _ in range(measured_samples):
        started_at = perf_counter()
        result = rank_scores(operation(), top_k)
        observations.append((perf_counter() - started_at) * 1000)
    return (
        RankingTiming(
            mean_ms=round(mean(observations), 6),
            p50_ms=round(median(observations), 6),
            p95_ms=round(percentile_nearest_rank(observations, 0.95), 6),
        ),
        result,
    )


def evaluate_contiguous_ranking(
    contract: NativeRankingContract,
    library_path: Path,
) -> NativeRankingReport:
    if contract.top_k > contract.row_count:
        raise ValueError("top_k cannot exceed row_count")
    capabilities = native_capabilities(library_path)
    if capabilities.backend != "native":
        raise ValueError(f"native ranking requires a library: {capabilities.fallback_reason}")
    query, rows = deterministic_contiguous_inputs(contract.dimensions, contract.row_count)
    fallback_timing, fallback_result = measure_ranking(
        lambda: cosine_batch_contiguous_fallback(
            query, rows, row_count=contract.row_count
        ),
        top_k=contract.top_k,
        warmup_samples=contract.warmup_samples,
        measured_samples=contract.measured_samples,
    )
    native_timing, native_result = measure_ranking(
        lambda: cosine_batch_contiguous(
            query,
            rows,
            row_count=contract.row_count,
            library_path=library_path,
        ),
        top_k=contract.top_k,
        warmup_samples=contract.warmup_samples,
        measured_samples=contract.measured_samples,
    )
    identity_match = [item[0] for item in fallback_result] == [
        item[0] for item in native_result
    ]
    maximum_error = max(
        abs(fallback[1] - native[1])
        for fallback, native in zip(fallback_result, native_result, strict=True)
    )
    speedup = fallback_timing.mean_ms / native_timing.mean_ms
    failures: list[str] = []
    if not identity_match:
        failures.append("native top-k identities differ from fallback")
    if maximum_error > contract.maximum_score_error:
        failures.append(
            f"top-k score error {maximum_error:.3e} exceeds {contract.maximum_score_error:.3e}"
        )
    if speedup < contract.minimum_speedup:
        failures.append(
            f"speedup {speedup:.3f} is below minimum {contract.minimum_speedup:.3f}"
        )
    return NativeRankingReport(
        generated_at=datetime.now(UTC),
        dimensions=contract.dimensions,
        row_count=contract.row_count,
        top_k=contract.top_k,
        input_bytes=(contract.row_count + 1) * contract.dimensions * 4,
        fallback=fallback_timing,
        native=native_timing,
        speedup=round(speedup, 6),
        top_k_identity_match=identity_match,
        maximum_top_k_score_error=maximum_error,
        threshold_failures=failures,
        native_build_info=capabilities.build_info,
    )


def load_native_ranking_contract(path: Path) -> NativeRankingContract:
    return NativeRankingContract.model_validate_json(path.read_text(encoding="utf-8"))


def write_native_ranking_report(report: NativeRankingReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json") | {"passed": report.passed}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def format_native_ranking_summary(report: NativeRankingReport) -> str:
    return "\n".join(
        [
            f"Native contiguous ranking: {'PASS' if report.passed else 'FAIL'}",
            f"Rows: {report.row_count}; dimensions: {report.dimensions}; top-k: {report.top_k}",
            f"Fallback P50: {report.fallback.p50_ms:.3f} ms",
            f"Native P50: {report.native.p50_ms:.3f} ms",
            f"Speedup: {report.speedup:.2f}x",
            f"Top-k identity match: {report.top_k_identity_match}",
        ]
    )
