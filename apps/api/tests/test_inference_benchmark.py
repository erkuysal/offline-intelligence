import argparse
import json
from pathlib import Path

import pytest

import manage
from app.evaluation.generation import GenerationReport
from app.evaluation.inference_benchmark import (
    ArtifactIdentity,
    BenchmarkContract,
    HardwareIdentity,
    InferenceMeasurement,
    PerformanceMetrics,
    ResourceMetrics,
    RuntimeIdentity,
    build_inference_benchmark_report,
)


ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = ROOT / "evaluation" / "baselines" / "generation-baseline-v1.json"
CONTRACT_PATH = ROOT / "config" / "models" / "gemma3-1b-q4-benchmark-v1.json"


def contract() -> BenchmarkContract:
    return BenchmarkContract.model_validate_json(CONTRACT_PATH.read_text(encoding="utf-8"))


def measurement(**performance_overrides: float) -> InferenceMeasurement:
    accepted = contract().artifact
    performance_values = {
        "cold_startup_ms": 900.0,
        "warmup_ms": 100.0,
        "sample_count": 20,
        "concurrency": 1,
        "mean_time_to_first_token_ms": 300.0,
        "p95_time_to_first_token_ms": 400.0,
        "mean_end_to_end_latency_ms": 700.0,
        "p95_end_to_end_latency_ms": 900.0,
        "mean_tokens_per_second": 30.0,
    }
    performance_values.update(performance_overrides)
    return InferenceMeasurement(
        measured_at="2026-07-19T12:00:00Z",
        artifact=accepted,
        runtime=RuntimeIdentity(
            name="llama.cpp",
            revision=contract().runtime_revision,
            executable="/opt/llama.cpp/llama-server",
            build="CUDA",
            context_size=4096,
            parallelism=1,
            configured_gpu_layers=99,
            gpu_offload_observed=True,
            flash_attention=True,
        ),
        hardware=HardwareIdentity(
            hostname="benchmark-host",
            operating_system="Linux",
            cpu="test-cpu",
            system_ram_mib=32768.0,
            gpu="test-gpu",
            gpu_vram_mib=12227.0,
            driver="test-driver",
        ),
        resources=ResourceMetrics(
            peak_process_ram_mib=2048.0,
            peak_gpu_vram_mib=3072.0,
            gpu_memory_measurement="per_process",
        ),
        performance=PerformanceMetrics(**performance_values),
    )


def quality_report(path: Path, **updates: object) -> GenerationReport:
    report = GenerationReport.model_validate_json(BASELINE_PATH.read_text(encoding="utf-8"))
    values = {
        "evaluation_mode": "base_rag",
        "adapter_id": None,
        "content_policy": "restricted",
        "case_output_policy": "redacted",
        "cases": [
            case.model_copy(update={"answer": "", "answer_persisted": False})
            for case in report.cases
        ],
    }
    values.update(updates)
    result = report.model_copy(update=values)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return GenerationReport.model_validate_json(path.read_text(encoding="utf-8"))


def test_build_report_accepts_matching_measurement_and_protected_evidence(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "protected-quality.json"
    report = build_inference_benchmark_report(
        contract(),
        measurement(),
        quality_report(evidence_path),
        quality_report_path=evidence_path,
    )

    assert report.passed is True
    assert report.identity_failures == []
    assert report.threshold_failures == []
    assert report.evaluation_evidence.content_policy == "restricted"
    assert report.evaluation_evidence.case_output_policy == "redacted"
    assert report.evaluation_evidence.sha256


def test_identity_mismatch_is_a_structured_failure(tmp_path: Path) -> None:
    evidence_path = tmp_path / "quality.json"
    measured = measurement().model_copy(
        update={
            "artifact": ArtifactIdentity(
                **(contract().artifact.model_dump() | {"sha256": "0" * 64})
            )
        }
    )

    report = build_inference_benchmark_report(
        contract(),
        measured,
        quality_report(evidence_path),
        quality_report_path=evidence_path,
    )

    assert report.passed is False
    assert any("artifact.sha256" in failure for failure in report.identity_failures)


def test_performance_and_quality_threshold_misses_are_structured(tmp_path: Path) -> None:
    evidence_path = tmp_path / "quality.json"
    rejected_quality = quality_report(
        evidence_path,
        threshold_failures=["restricted fact leak count 1 exceeds maximum 0"],
    )

    report = build_inference_benchmark_report(
        contract(),
        measurement(
            mean_time_to_first_token_ms=800.0,
            p95_time_to_first_token_ms=900.0,
            mean_end_to_end_latency_ms=1000.0,
            p95_end_to_end_latency_ms=1100.0,
            mean_tokens_per_second=10.0,
        ),
        rejected_quality,
        quality_report_path=evidence_path,
    )

    assert report.passed is False
    assert any("mean TTFT" in failure for failure in report.threshold_failures)
    assert any("mean throughput" in failure for failure in report.threshold_failures)
    assert "protected quality evaluation did not pass" in report.threshold_failures


def test_measurement_rejects_end_to_end_latency_below_ttft() -> None:
    with pytest.raises(ValueError, match="mean end-to-end latency cannot be lower"):
        measurement(
            mean_time_to_first_token_ms=800.0,
            mean_end_to_end_latency_ms=700.0,
        )


def test_cli_returns_nonzero_and_writes_report_for_gate_failure(tmp_path: Path) -> None:
    measurement_path = tmp_path / "measurement.json"
    measurement_path.write_text(
        measurement(mean_tokens_per_second=10.0).model_dump_json(indent=2),
        encoding="utf-8",
    )
    quality_path = tmp_path / "quality.json"
    quality_report(quality_path)
    output = tmp_path / "benchmark.json"

    status = manage.build_inference_benchmark(
        argparse.Namespace(
            contract=str(CONTRACT_PATH),
            measurement=str(measurement_path),
            quality_report=str(quality_path),
            output=str(output),
        )
    )

    assert status == 1
    assert json.loads(output.read_text(encoding="utf-8"))["threshold_failures"]


def test_cli_returns_two_and_does_not_write_report_for_invalid_input(tmp_path: Path) -> None:
    measurement_path = tmp_path / "invalid.json"
    measurement_path.write_text("{}", encoding="utf-8")
    quality_path = tmp_path / "quality.json"
    quality_report(quality_path)
    output = tmp_path / "benchmark.json"

    status = manage.build_inference_benchmark(
        argparse.Namespace(
            contract=str(CONTRACT_PATH),
            measurement=str(measurement_path),
            quality_report=str(quality_path),
            output=str(output),
        )
    )

    assert status == 2
    assert not output.exists()
