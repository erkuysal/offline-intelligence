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


def load_root_env(profile: str = "development") -> Path | None:
    configure_import_path()

    from app.env_files import load_env_file

    return load_env_file(profile)


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

    load_root_env("test")
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
            "DOCUMENT_INGESTION_MODE": "sync",
            "LLM_BACKEND": "fake",
            "LLM_WARMUP_ENABLED": "false",
            "EMBEDDING_BACKEND": "fake",
            "EMBEDDING_MODEL": "fake-bow",
        }
    )
    return environment


def build_e2e_environment() -> dict[str, str]:
    from sqlalchemy.engine import make_url

    load_root_env("e2e")
    configured_url = os.environ.get("E2E_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not configured_url:
        raise RuntimeError("DATABASE_URL or E2E_DATABASE_URL must be configured")

    database_url = make_url(configured_url)
    database_name = database_url.database or ""
    if not database_name:
        raise RuntimeError("The configured E2E database URL must include a database name")
    if not database_name.endswith("_e2e"):
        database_url = database_url.set(database=f"{database_name}_e2e")

    admin_url = os.environ.get("E2E_DATABASE_ADMIN_URL")
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
            "E2E_DATABASE_ADMIN_URL": admin_url,
            "DOCUMENT_STORAGE_DIR": os.environ.get(
                "E2E_DOCUMENT_STORAGE_DIR",
                "/tmp/offline-intelligence-hub-e2e/documents",
            ),
            "DOCUMENT_INGESTION_MODE": "sync",
            "LLM_BACKEND": "fake",
            "LLM_WARMUP_ENABLED": "false",
            "EMBEDDING_BACKEND": "fake",
            "EMBEDDING_MODEL": "fake-bow",
        }
    )
    return environment


def e2e_setup(_args: argparse.Namespace) -> int:
    configure_import_path()
    try:
        environment = build_e2e_environment()
    except (RuntimeError, ValueError) as exc:
        print(f"E2E setup failed: {exc}", file=sys.stderr)
        return 2

    prepare_status = run_subprocess(
        [sys.executable, str(ROOT / "scripts" / "e2e" / "environment.py"), "setup"],
        environment=environment,
    )
    if prepare_status != 0:
        return prepare_status
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
        environment=environment,
    )


def e2e_cleanup(_args: argparse.Namespace) -> int:
    configure_import_path()
    try:
        environment = build_e2e_environment()
    except (RuntimeError, ValueError) as exc:
        print(f"E2E cleanup failed: {exc}", file=sys.stderr)
        return 2
    return run_subprocess(
        [sys.executable, str(ROOT / "scripts" / "e2e" / "environment.py"), "cleanup"],
        environment=environment,
    )


def test(args: argparse.Namespace) -> int:
    configure_import_path()
    try:
        environment = build_test_environment()
    except (RuntimeError, ValueError) as exc:
        print(f"Test setup failed: {exc}", file=sys.stderr)
        return 2

    prepare_status = run_subprocess(
        [sys.executable, str(ROOT / "scripts" / "db" / "prepare-test.py")],
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
    return run_subprocess(
        ["docker", "compose", "-f", "deploy/compose.yaml", "run", "--build", "--rm", "api-tests"]
    )


def lint(_args: argparse.Namespace) -> int:
    configure_import_path()
    return run_subprocess([sys.executable, "-m", "ruff", "check", "."])


def typecheck(_args: argparse.Namespace) -> int:
    configure_import_path()
    return run_subprocess([sys.executable, "-m", "mypy", "apps/api/app"])


def smoke(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "smoke.sh")])


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
        ["bash", str(ROOT / "scripts" / "models" / "start-llm.sh")],
        cwd=ROOT,
        env=environment,
    )


def llm_check(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "models" / "check-llm.sh")])


def llm_stop(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "models" / "stop-llm.sh")])


def embedding_start(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "models" / "start-embedding.sh")])


def embedding_check(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "models" / "check-embedding.sh")])


def embedding_stop(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "models" / "stop-embedding.sh")])


def embedding_reindex(args: argparse.Namespace) -> int:
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
                stale_only=args.stale_only,
            )
    except EmbeddingError as exc:
        print(f"Embedding reindex failed: {exc}", file=sys.stderr)
        return 1

    qualifier = "stale " if args.stale_only else ""
    print(f"Re-embedded {processed} {qualifier}document chunks with {settings.embedding_model}")
    return 0


def ingestion_worker(args: argparse.Namespace) -> int:
    configure_import_path()
    load_root_env()

    from redis.exceptions import RedisError

    from app.cache.redis import get_redis_client
    from app.config import get_settings
    from app.services.document_ingestion_queue import process_next_ingestion_job
    from app.services.document_ingestion_queue import recover_reserved_ingestion_jobs

    settings = get_settings()
    redis_client = get_redis_client()

    try:
        recovered = recover_reserved_ingestion_jobs(
            redis_client,
            queue_name=settings.document_ingestion_queue_name,
        )
        if recovered:
            print(f"Recovered {recovered} interrupted document ingestion jobs")
        while True:
            processed = process_next_ingestion_job(redis_client, settings=settings)
            if args.once:
                if processed:
                    print("Processed one document ingestion job")
                    return 0
                print("No document ingestion job available")
                return 0
    except RedisError as exc:
        print(f"Document ingestion worker failed: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="./manage.py",
        description="Offline Intelligence Hub development commands",
    )
    parser.add_argument(
        "--env-file",
        help="override the command's profile environment file",
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

    e2e_setup_parser = subparsers.add_parser(
        "e2e-setup",
        help="create and migrate the isolated browser-test environment",
    )
    e2e_setup_parser.set_defaults(func=e2e_setup)

    e2e_cleanup_parser = subparsers.add_parser(
        "e2e-cleanup",
        help="clear data and files from the isolated browser-test environment",
    )
    e2e_cleanup_parser.set_defaults(func=e2e_cleanup)

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
        help="load config/models/<profile>.env or a profile file path",
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
    embedding_reindex_parser.add_argument(
        "--stale-only",
        action="store_true",
        help="only re-embed chunks missing vectors or using another embedding model",
    )
    embedding_reindex_parser.set_defaults(func=embedding_reindex)

    ingestion_worker_parser = subparsers.add_parser(
        "ingestion-worker",
        help="process queued document ingestion jobs from Redis",
    )
    ingestion_worker_parser.add_argument("--once", action="store_true", help="process at most one queued job")
    ingestion_worker_parser.set_defaults(func=ingestion_worker)

    return parser


def main() -> int:
    configure_import_path()
    parser = build_parser()
    args = parser.parse_args()
    if args.env_file:
        os.environ["APP_ENV_FILE"] = args.env_file
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
