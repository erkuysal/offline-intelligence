import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "e2e" / "environment.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("manage_e2e_environment", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_environment_accepts_dedicated_e2e_resources(monkeypatch, tmp_path) -> None:
    storage_root = tmp_path / "offline-intelligence-hub-e2e"
    storage_dir = storage_root / "documents"
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/offline_ai_e2e")
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("E2E_DOCUMENT_STORAGE_ROOT", str(storage_root))
    script = load_script()

    _, database_name, resolved_storage = script.validate_environment()

    assert database_name == "offline_ai_e2e"
    assert resolved_storage == storage_dir


def test_validate_environment_rejects_non_e2e_database(monkeypatch, tmp_path) -> None:
    storage_root = tmp_path / "offline-intelligence-hub-e2e"
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/offline_ai")
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", str(storage_root / "documents"))
    monkeypatch.setenv("E2E_DOCUMENT_STORAGE_ROOT", str(storage_root))
    script = load_script()

    with pytest.raises(RuntimeError, match="non-E2E database"):
        script.validate_environment()


def test_validate_environment_rejects_storage_outside_e2e_root(monkeypatch, tmp_path) -> None:
    storage_root = tmp_path / "offline-intelligence-hub-e2e"
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/offline_ai_e2e")
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("E2E_DOCUMENT_STORAGE_ROOT", str(storage_root))
    script = load_script()

    with pytest.raises(RuntimeError, match="storage outside"):
        script.validate_environment()
