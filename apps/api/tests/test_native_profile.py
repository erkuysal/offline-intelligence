import argparse
from array import array
import json
import math
from pathlib import Path

import pytest

import manage
from app.evaluation.native_profile import (
    NativeProfileContract,
    ProfileWorkload,
    build_native_profile_report,
)
from app.native.vector_similarity import (
    cosine_batch,
    cosine_batch_contiguous_fallback,
    cosine_batch_fallback,
    cosine_similarity_fallback,
    native_capabilities,
)
from app.evaluation import native_verification as verification
from app.evaluation.native_verification import NativeVerificationContract


def small_contract() -> NativeProfileContract:
    return NativeProfileContract(
        warmup_samples=0,
        measured_samples=3,
        workloads=[ProfileWorkload(dimensions=3, batch_size=2, calls_per_sample=1)],
    )


def small_verification_contract() -> NativeVerificationContract:
    return NativeVerificationContract(
        fuzz_seed=8,
        fuzz_cases=5,
        fuzz_max_dimensions=8,
        fuzz_max_batch_size=3,
        absolute_tolerance=1e-6,
        relative_tolerance=1e-5,
        relative_epsilon=1e-8,
        warmup_samples=0,
        measured_samples=3,
        performance_workloads=[
            ProfileWorkload(dimensions=3, batch_size=2, calls_per_sample=1)
        ],
    )


def test_python_cosine_fallback_has_explicit_numerical_contract() -> None:
    assert cosine_similarity_fallback([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity_fallback([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert math.isclose(
        cosine_batch_fallback([1.0, 1.0], [[1.0, 0.0], [-1.0, 0.0]])[0],
        math.sqrt(0.5),
    )

    with pytest.raises(ValueError, match="non-empty"):
        cosine_similarity_fallback([], [])
    with pytest.raises(ValueError, match="non-zero"):
        cosine_batch_fallback([1.0, 0.0], [[0.0, 0.0]])
    with pytest.raises(ValueError, match="dimensions"):
        cosine_batch_fallback([1.0, 0.0], [[1.0]])


def test_public_api_falls_back_when_library_is_unavailable(tmp_path: Path) -> None:
    missing = tmp_path / "missing-vector-library.so"

    assert cosine_batch([1.0, 0.0], [[1.0, 0.0]], library_path=missing) == [1.0]
    capabilities = native_capabilities(missing)
    assert capabilities.backend == "python"
    assert capabilities.abi_version is None
    assert capabilities.fallback_reason
    with pytest.raises(ValueError, match="finite"):
        cosine_batch([float("nan")], [[1.0]], library_path=missing)


def test_contiguous_fallback_preserves_row_major_shape() -> None:
    scores = cosine_batch_contiguous_fallback(
        array("f", [1.0, 0.0]),
        array("f", [1.0, 0.0, 0.0, 1.0]),
        row_count=2,
    )

    assert scores == [1.0, 0.0]
    with pytest.raises(ValueError, match="shape"):
        cosine_batch_contiguous_fallback(
            array("f", [1.0, 0.0]),
            array("f", [1.0]),
            row_count=1,
        )


def test_profile_records_host_workload_and_non_production_decision() -> None:
    report = build_native_profile_report(small_contract())

    assert report.decision == "proceed_experimental_only"
    assert report.production_dense_retrieval_owner == "postgresql_pgvector"
    assert report.production_path_selected is False
    assert len(report.measurements) == 1
    measurement = report.measurements[0]
    assert measurement.dimensions == 3
    assert measurement.batch_size == 2
    assert measurement.input_bytes_per_call == 36
    assert measurement.mean_latency_ms > 0
    assert measurement.mean_vectors_per_second > 0


def test_contract_rejects_duplicate_workloads() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        NativeProfileContract(
            workloads=[
                ProfileWorkload(dimensions=3, batch_size=2),
                ProfileWorkload(dimensions=3, batch_size=2),
            ]
        )


def test_native_profile_cli_writes_machine_report(tmp_path: Path) -> None:
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(small_contract().model_dump_json(), encoding="utf-8")
    output = tmp_path / "report.json"

    status = manage.profile_native_vector_candidate(
        argparse.Namespace(contract=str(contract_path), output=str(output))
    )

    assert status == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["report_type"] == "native_vector_profile"
    assert report["measurements"][0]["implementation"] == "python_scalar"


def test_native_profile_cli_rejects_invalid_contract(tmp_path: Path) -> None:
    contract_path = tmp_path / "contract.json"
    contract_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "report.json"

    status = manage.profile_native_vector_candidate(
        argparse.Namespace(contract=str(contract_path), output=str(output))
    )

    assert status == 2
    assert not output.exists()


def test_deterministic_fuzz_gate_records_zero_failures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        verification,
        "cosine_batch",
        lambda query, rows, library_path: cosine_batch_fallback(query, rows),
    )

    result = verification.verify_numerical_equivalence(
        small_verification_contract(),
        tmp_path / "unused.so",
    )

    assert result.case_count == 5
    assert result.value_count >= 5
    assert result.failure_count == 0
    assert result.passed is True


def test_native_verification_cli_rejects_missing_library(tmp_path: Path) -> None:
    contract_path = tmp_path / "verification.json"
    contract_path.write_text(
        small_verification_contract().model_dump_json(), encoding="utf-8"
    )
    output = tmp_path / "report.json"

    status = manage.verify_native_vector_candidate(
        argparse.Namespace(
            contract=str(contract_path),
            library=str(tmp_path / "missing.so"),
            output=str(output),
        )
    )

    assert status == 2
    assert not output.exists()
