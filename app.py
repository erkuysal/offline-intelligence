#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API_PATH = ROOT / "apps" / "api"


def configure_import_path() -> None:
    api_path = str(API_PATH)
    if api_path not in sys.path:
        sys.path.insert(0, api_path)

    current_pythonpath = os.environ.get("PYTHONPATH")
    if current_pythonpath:
        paths = current_pythonpath.split(os.pathsep)
        if api_path not in paths:
            os.environ["PYTHONPATH"] = os.pathsep.join([api_path, current_pythonpath])
    else:
        os.environ["PYTHONPATH"] = api_path

    app_module = sys.modules.get("app")
    if app_module is not None and not hasattr(app_module, "__path__"):
        del sys.modules["app"]


def run_subprocess(
    args: Sequence[str],
    cwd: Path = ROOT,
    environment: Mapping[str, str] | None = None,
) -> int:
    return subprocess.call(args, cwd=cwd, env=environment)


def load_root_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        os.environ.setdefault(key, value)


def runserver(_args: argparse.Namespace) -> int:
    configure_import_path()

    from app.main import main

    main()
    return 0


def migrate(_args: argparse.Namespace) -> int:
    configure_import_path()
    load_root_env()
    return run_subprocess(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ROOT / "alembic.ini"),
            "upgrade",
            "head",
        ],
        cwd=API_PATH,
    )


def build_test_environment() -> dict[str, str]:
    from sqlalchemy.engine import make_url

    load_root_env()
    configured_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not configured_url:
        raise RuntimeError("DATABASE_URL or TEST_DATABASE_URL must be configured")

    database_url = make_url(configured_url)
    database_name = database_url.database or ""
    if not database_name:
        raise RuntimeError("The configured test database URL must include a database name")
    if not database_name.endswith("_test"):
        database_url = database_url.set(database=f"{database_name}_test")

    admin_url = os.environ.get("TEST_DATABASE_ADMIN_URL")
    if not admin_url:
        admin_url = database_url.set(
            drivername=database_url.drivername.split("+", 1)[0],
            database="postgres",
        ).render_as_string(hide_password=False)

    environment = os.environ.copy()
    environment.update(
        {
            "ENVIRONMENT": "testing",
            "DATABASE_URL": database_url.render_as_string(hide_password=False),
            "TEST_DATABASE_ADMIN_URL": admin_url,
            "DOCUMENT_STORAGE_DIR": os.environ.get(
                "TEST_DOCUMENT_STORAGE_DIR",
                "/tmp/offline-intelligence-hub-tests/documents",
            ),
            "LLM_BACKEND": "fake",
            "LLM_WARMUP_ENABLED": "false",
            "EMBEDDING_BACKEND": "fake",
        }
    )
    return environment


def test(args: argparse.Namespace) -> int:
    configure_import_path()
    try:
        environment = build_test_environment()
    except (RuntimeError, ValueError) as exc:
        print(f"Test setup failed: {exc}", file=sys.stderr)
        return 2

    prepare_status = run_subprocess(
        [sys.executable, str(ROOT / "scripts" / "prepare_test_database.py")],
        environment=environment,
    )
    if prepare_status != 0:
        return prepare_status

    migration_status = run_subprocess(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ROOT / "alembic.ini"),
            "upgrade",
            "head",
        ],
        cwd=API_PATH,
        environment=environment,
    )
    if migration_status != 0:
        return migration_status

    pytest_args = args.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]

    command = [sys.executable, "-m", "pytest"]
    if pytest_args:
        command.extend(pytest_args)
    else:
        command.append("-q")
    return run_subprocess(command, environment=environment)


def test_container(_args: argparse.Namespace) -> int:
    return run_subprocess(["docker", "compose", "run", "--build", "--rm", "api-tests"])


def lint(_args: argparse.Namespace) -> int:
    configure_import_path()
    return run_subprocess([sys.executable, "-m", "ruff", "check", "."])


def typecheck(_args: argparse.Namespace) -> int:
    configure_import_path()
    return run_subprocess([sys.executable, "-m", "mypy", "apps/api/app"])


def smoke(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "smoke_test.sh")])


def llm_probe(args: argparse.Namespace) -> int:
    configure_import_path()
    load_root_env()

    from app.schemas.chat import ChatCompletionRequest, ChatMessage
    from app.services.llm import LLMError, get_llm_backend

    request = ChatCompletionRequest(
        messages=[
            ChatMessage(role="user", content=args.prompt),
        ],
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )

    try:
        response = get_llm_backend().complete_chat(request)
    except LLMError as exc:
        print(f"LLM probe failed: {exc}", file=sys.stderr)
        return 1

    print(response.choices[0].message.content)
    return 0


def llm_start(args: argparse.Namespace) -> int:
    environment = os.environ.copy()
    if args.profile:
        environment["LLAMA_PROFILE"] = args.profile
    return subprocess.call(
        ["bash", str(ROOT / "scripts" / "start_llama_server.sh")],
        cwd=ROOT,
        env=environment,
    )


def llm_check(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "check_llama_server.sh")])


def llm_stop(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "stop_llama_server.sh")])


def embedding_start(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "start_embedding_server.sh")])


def embedding_check(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "check_embedding_server.sh")])


def embedding_stop(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "stop_embedding_server.sh")])


def embedding_reindex(_args: argparse.Namespace) -> int:
    configure_import_path()
    load_root_env()

    from app.config import get_settings
    from app.db.session import SessionLocal
    from app.services.embeddings import (
        EmbeddingError,
        get_embedding_provider,
        reembed_all_document_chunks,
    )

    settings = get_settings()
    try:
        with SessionLocal() as db:
            processed = reembed_all_document_chunks(
                db,
                provider=get_embedding_provider(),
                batch_size=settings.embedding_reindex_batch_size,
            )
    except EmbeddingError as exc:
        print(f"Embedding reindex failed: {exc}", file=sys.stderr)
        return 1

    print(f"Re-embedded {processed} document chunks with {settings.embedding_model}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="./app.py",
        description="Offline Intelligence Hub development commands",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    runserver_parser = subparsers.add_parser("runserver", help="start the API server")
    runserver_parser.set_defaults(func=runserver)

    migrate_parser = subparsers.add_parser("migrate", help="apply database migrations")
    migrate_parser.set_defaults(func=migrate)

    test_parser = subparsers.add_parser("test", help="run the test suite")
    test_parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    test_parser.set_defaults(func=test)

    test_container_parser = subparsers.add_parser(
        "test-container",
        help="run the test suite inside Docker Compose",
    )
    test_container_parser.set_defaults(func=test_container)

    lint_parser = subparsers.add_parser("lint", help="run ruff")
    lint_parser.set_defaults(func=lint)

    typecheck_parser = subparsers.add_parser("typecheck", help="run mypy")
    typecheck_parser.set_defaults(func=typecheck)

    smoke_parser = subparsers.add_parser("smoke", help="run the HTTP smoke test")
    smoke_parser.set_defaults(func=smoke)

    llm_probe_parser = subparsers.add_parser(
        "llm-probe",
        help="send a prompt to the configured LLM backend",
    )
    llm_probe_parser.add_argument(
        "prompt",
        nargs="?",
        default="Say hello from the local LLM probe.",
    )
    llm_probe_parser.add_argument("--max-tokens", type=int, default=128)
    llm_probe_parser.add_argument("--temperature", type=float, default=0.2)
    llm_probe_parser.set_defaults(func=llm_probe)

    llm_start_parser = subparsers.add_parser(
        "llm-start",
        help="start the configured llama.cpp server",
    )
    llm_start_parser.add_argument(
        "--profile",
        help="load scripts/llama_profiles/<profile>.env or a profile file path",
    )
    llm_start_parser.set_defaults(func=llm_start)

    llm_check_parser = subparsers.add_parser(
        "llm-check",
        help="check the configured llama.cpp server",
    )
    llm_check_parser.set_defaults(func=llm_check)

    llm_stop_parser = subparsers.add_parser(
        "llm-stop",
        help="gracefully stop the configured llama.cpp server",
    )
    llm_stop_parser.set_defaults(func=llm_stop)

    embedding_start_parser = subparsers.add_parser(
        "embedding-start",
        help="start the dedicated llama.cpp embedding server",
    )
    embedding_start_parser.set_defaults(func=embedding_start)

    embedding_check_parser = subparsers.add_parser(
        "embedding-check",
        help="check the dedicated embedding server",
    )
    embedding_check_parser.set_defaults(func=embedding_check)

    embedding_stop_parser = subparsers.add_parser(
        "embedding-stop",
        help="gracefully stop the dedicated embedding server",
    )
    embedding_stop_parser.set_defaults(func=embedding_stop)

    embedding_reindex_parser = subparsers.add_parser(
        "embedding-reindex",
        help="replace stored document chunk embeddings using the configured provider",
    )
    embedding_reindex_parser.set_defaults(func=embedding_reindex)

    return parser


def main() -> int:
    configure_import_path()
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
