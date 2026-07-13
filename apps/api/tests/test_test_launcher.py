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
