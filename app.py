#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
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


def run_subprocess(args: Sequence[str], cwd: Path = ROOT) -> int:
    return subprocess.call(args, cwd=cwd)


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


def test(args: argparse.Namespace) -> int:
    configure_import_path()
    command = [sys.executable, "-m", "pytest"]
    if args.pytest_args:
        command.extend(args.pytest_args)
    else:
        command.append("-q")
    return run_subprocess(command)


def test_container(_args: argparse.Namespace) -> int:
    return run_subprocess(["docker", "compose", "run", "--build", "--rm", "api-tests"])


def lint(_args: argparse.Namespace) -> int:
    configure_import_path()
    return run_subprocess([sys.executable, "-m", "ruff", "check", "."])


def smoke(_args: argparse.Namespace) -> int:
    return run_subprocess(["bash", str(ROOT / "scripts" / "smoke_test.sh")])


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

    smoke_parser = subparsers.add_parser("smoke", help="run the HTTP smoke test")
    smoke_parser.set_defaults(func=smoke)

    return parser


def main() -> int:
    configure_import_path()
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
