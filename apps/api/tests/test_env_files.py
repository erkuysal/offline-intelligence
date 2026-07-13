import os
from pathlib import Path

from app.env_files import load_env_file, resolve_env_file, resolve_env_files


def test_resolve_env_file_uses_profile_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("APP_ENV_FILE", raising=False)
    profile_file = tmp_path / "config" / "env" / "test.env"
    profile_file.parent.mkdir(parents=True)
    profile_file.touch()

    assert resolve_env_file("test", root=tmp_path) == profile_file


def test_resolve_env_file_honors_explicit_relative_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV_FILE", "config/custom.env")

    assert resolve_env_file(root=tmp_path) == tmp_path / "config/custom.env"


def test_load_env_file_parses_values_without_overwriting_environment(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / "custom.env"
    env_file.write_text('PROFILE_VALUE="from file"\nEXISTING_VALUE=from-file\n', encoding="utf-8")
    monkeypatch.setenv("APP_ENV_FILE", str(env_file))
    monkeypatch.setenv("EXISTING_VALUE", "from-environment")
    monkeypatch.delenv("PROFILE_VALUE", raising=False)

    loaded_file = load_env_file()

    assert loaded_file == env_file
    assert Path(loaded_file).is_absolute()
    assert os.environ["PROFILE_VALUE"] == "from file"
    assert os.environ["EXISTING_VALUE"] == "from-environment"


def test_development_profile_layers_legacy_local_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("APP_ENV_FILE", raising=False)
    env_dir = tmp_path / "config" / "env"
    env_dir.mkdir(parents=True)
    (env_dir / "dev.env").write_text("LLM_BACKEND=fake\nPORT=8000\n", encoding="utf-8")
    (env_dir / "local.env").write_text("LLM_BACKEND=openai_compatible\n", encoding="utf-8")

    assert resolve_env_files("development", root=tmp_path) == (
        env_dir / "dev.env",
        env_dir / "local.env",
    )
