import os
from pathlib import Path

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE_VARIABLE = "APP_ENV_FILE"
PROFILE_ENV_FILES = {
    "dev": ".env.dev",
    "development": ".env.dev",
    "test": ".env.test",
    "testing": ".env.test",
    "e2e": ".env.e2e",
    "production": ".env.production",
}


def resolve_env_file(profile: str | None = None, *, root: Path = PROJECT_ROOT) -> Path | None:
    configured_file = os.environ.get(ENV_FILE_VARIABLE)
    if configured_file:
        path = Path(configured_file).expanduser()
        return path if path.is_absolute() else root / path

    normalized_profile = (profile or os.environ.get("ENVIRONMENT") or "development").lower()
    profile_file = root / PROFILE_ENV_FILES.get(normalized_profile, f".env.{normalized_profile}")
    if profile_file.is_file():
        return profile_file

    legacy_file = root / ".env"
    return legacy_file if legacy_file.is_file() else None


def resolve_env_files(profile: str | None = None, *, root: Path = PROJECT_ROOT) -> tuple[Path, ...]:
    primary_file = resolve_env_file(profile, root=root)
    if primary_file is None:
        return ()

    normalized_profile = (profile or os.environ.get("ENVIRONMENT") or "development").lower()
    explicit_file = os.environ.get(ENV_FILE_VARIABLE)
    legacy_file = root / ".env"
    if (
        explicit_file is None
        and normalized_profile in {"dev", "development"}
        and primary_file != legacy_file
        and legacy_file.is_file()
    ):
        return primary_file, legacy_file
    return (primary_file,)


def load_env_file(profile: str | None = None, *, override: bool = False) -> Path | None:
    env_files = resolve_env_files(profile)
    if not env_files:
        return None

    values: dict[str, str | None] = {}
    for env_file in env_files:
        values.update(dotenv_values(env_file))
    for key, value in values.items():
        if value is None:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
    return env_files[0]
