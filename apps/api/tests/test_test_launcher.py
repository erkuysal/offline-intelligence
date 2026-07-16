import importlib.util
from pathlib import Path
from types import ModuleType

from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_PATH = ROOT / "manage.py"
if not LAUNCHER_PATH.exists():
    LAUNCHER_PATH = ROOT / "launcher.py"


def load_launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("offline_hub_launcher", LAUNCHER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_test_environment_derives_isolated_database(monkeypatch) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_ADMIN_URL", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://offline_ai:offline_ai@localhost:5432/offline_ai",
    )
    launcher = load_launcher()

    environment = launcher.build_test_environment()

    assert environment["ENVIRONMENT"] == "testing"
    assert make_url(environment["DATABASE_URL"]).database == "offline_ai_test"
    assert make_url(environment["TEST_DATABASE_ADMIN_URL"]).database == "postgres"
    assert environment["LLM_BACKEND"] == "fake"
    assert environment["EMBEDDING_BACKEND"] == "fake"
    assert environment["RERANKER_BACKEND"] == "disabled"
    assert environment["QUERY_REWRITE_BACKEND"] == "disabled"


def test_build_test_environment_preserves_explicit_test_database(monkeypatch) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://offline_ai:offline_ai@localhost:5432/custom_test",
    )
    monkeypatch.setenv(
        "TEST_DATABASE_ADMIN_URL",
        "postgresql://offline_ai:offline_ai@localhost:5432/postgres",
    )
    launcher = load_launcher()

    environment = launcher.build_test_environment()

    assert make_url(environment["DATABASE_URL"]).database == "custom_test"


def test_build_e2e_environment_derives_isolated_database(monkeypatch) -> None:
    monkeypatch.delenv("E2E_DATABASE_URL", raising=False)
    monkeypatch.delenv("E2E_DATABASE_ADMIN_URL", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://offline_ai:offline_ai@localhost:5432/offline_ai",
    )
    launcher = load_launcher()

    environment = launcher.build_e2e_environment()

    assert environment["ENVIRONMENT"] == "testing"
    assert make_url(environment["DATABASE_URL"]).database == "offline_ai_e2e"
    assert make_url(environment["E2E_DATABASE_ADMIN_URL"]).database == "postgres"
    assert environment["DOCUMENT_STORAGE_DIR"].endswith("offline-intelligence-hub-e2e/documents")
    assert environment["DOCUMENT_INGESTION_MODE"] == "sync"
    assert environment["LLM_BACKEND"] == "fake"
    assert environment["EMBEDDING_BACKEND"] == "fake"
    assert environment["RERANKER_BACKEND"] == "disabled"
    assert environment["QUERY_REWRITE_BACKEND"] == "disabled"


def test_build_e2e_environment_preserves_explicit_e2e_database(monkeypatch) -> None:
    monkeypatch.setenv(
        "E2E_DATABASE_URL",
        "postgresql+psycopg://offline_ai:offline_ai@localhost:5432/custom_e2e",
    )
    monkeypatch.setenv(
        "E2E_DATABASE_ADMIN_URL",
        "postgresql://offline_ai:offline_ai@localhost:5432/postgres",
    )
    launcher = load_launcher()

    environment = launcher.build_e2e_environment()

    assert make_url(environment["DATABASE_URL"]).database == "custom_e2e"


def test_parser_exposes_retrieval_cleanup_command() -> None:
    launcher = load_launcher()

    args = launcher.build_parser().parse_args(["retrieval-cleanup"])

    assert args.func is launcher.retrieval_cleanup


def test_parser_accepts_lexical_evaluation_strategy() -> None:
    launcher = load_launcher()

    args = launcher.build_parser().parse_args(["evaluate-retrieval", "--strategy", "lexical"])

    assert args.strategy == "lexical"

    hybrid_args = launcher.build_parser().parse_args(
        ["evaluate-retrieval", "--strategy", "hybrid"]
    )
    assert hybrid_args.strategy == "hybrid"
    reranked_args = launcher.build_parser().parse_args(
        ["evaluate-retrieval", "--strategy", "reranked"]
    )
    assert reranked_args.strategy == "reranked"
    multi_query_args = launcher.build_parser().parse_args(
        ["evaluate-retrieval", "--strategy", "multi_query"]
    )
    assert multi_query_args.strategy == "multi_query"


def test_parser_exposes_reranker_lifecycle_commands() -> None:
    launcher = load_launcher()

    assert launcher.build_parser().parse_args(["reranker-start"]).func is launcher.reranker_start
    assert launcher.build_parser().parse_args(["reranker-check"]).func is launcher.reranker_check
    assert launcher.build_parser().parse_args(["reranker-stop"]).func is launcher.reranker_stop


def test_parser_exposes_generation_evaluation_thresholds() -> None:
    launcher = load_launcher()

    args = launcher.build_parser().parse_args(
        [
            "evaluate-generation",
            "--mode",
            "base",
            "--min-faithfulness",
            "0.9",
            "--max-hallucination",
            "0.1",
        ]
    )

    assert args.func is launcher.evaluate_generation
    assert args.mode == "base"
    assert args.min_faithfulness == 0.9
    assert args.max_hallucination == 0.1


def test_parser_exposes_training_evaluation_matrix() -> None:
    launcher = load_launcher()

    args = launcher.build_parser().parse_args(
        [
            "training-evaluation-matrix",
            "--base",
            "base.json",
            "--base-rag",
            "base-rag.json",
            "--adapter",
            "adapter.json",
            "--adapter-rag",
            "adapter-rag.json",
            "--base-rag-regression",
            "phase4-base-rag.json",
            "--adapter-rag-regression",
            "phase4-adapter-rag.json",
            "--min-supported-refusal",
            "1",
        ]
    )

    assert args.func is launcher.build_training_evaluation_matrix
    assert args.min_supported_refusal == 1.0


def test_parser_exposes_training_evaluation_evidence_index() -> None:
    launcher = load_launcher()

    args = launcher.build_parser().parse_args(
        [
            "training-evaluation-index",
            "--dataset-validation",
            "validation.json",
            "--training-run",
            "training.json",
            "--held-out-behavior",
            "held-out.json",
            "--runtime",
            "base.json",
            "--runtime",
            "base-rag.json",
            "--runtime",
            "adapter.json",
            "--runtime",
            "adapter-rag.json",
            "--regression-runtime",
            "phase4-base-rag.json",
            "--regression-runtime",
            "phase4-adapter-rag.json",
        ]
    )

    assert args.func is launcher.build_training_evaluation_index
    assert len(args.runtime) == 4
    assert len(args.regression_runtime) == 2


def test_parser_exposes_training_foundation_commands() -> None:
    launcher = load_launcher()

    preflight = launcher.build_parser().parse_args(["training-preflight"])
    calibration = launcher.build_parser().parse_args(
        ["training-calibrate", "--local-files-only"]
    )
    template = launcher.build_parser().parse_args(
        ["training-template-check", "--local-files-only"]
    )
    continuity = launcher.build_parser().parse_args(
        ["training-continuity", "--runtime-url", "http://localhost:9999/v1"]
    )
    data_validation = launcher.build_parser().parse_args(
        ["training-data-validate", "--manifest", "training/datasets/example/manifest.json"]
    )
    training_run = launcher.build_parser().parse_args(
        [
            "training-run",
            "--manifest",
            "training/datasets/phase5/manifest.json",
            "--output-dir",
            "var/training/runs/candidate-1",
            "--rank",
            "16",
            "--learning-rate",
            "0.0002",
            "--local-files-only",
        ]
    )

    assert preflight.func is launcher.training_preflight
    assert preflight.config.endswith("gemma3-1b-lora-v1.json")
    assert calibration.func is launcher.training_calibrate
    assert calibration.local_files_only is True
    assert template.func is launcher.training_template_check
    assert template.local_files_only is True
    assert continuity.func is launcher.training_continuity
    assert continuity.runtime_url == "http://localhost:9999/v1"
    assert data_validation.func is launcher.training_data_validate
    assert data_validation.manifest.endswith("manifest.json")
    assert training_run.func is launcher.training_run
    assert training_run.rank == 16
    assert training_run.learning_rate == 0.0002
    assert training_run.local_files_only is True
