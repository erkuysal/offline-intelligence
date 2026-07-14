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
            "--min-faithfulness",
            "0.9",
            "--max-hallucination",
            "0.1",
        ]
    )

    assert args.func is launcher.evaluate_generation
    assert args.min_faithfulness == 0.9
    assert args.max_hallucination == 0.1
