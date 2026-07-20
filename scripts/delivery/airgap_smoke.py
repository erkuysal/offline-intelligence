#!/usr/bin/env python3
"""Run a dependency-free, machine-readable air-gap application smoke probe."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import secrets
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    duration_ms: float
    detail: str


class SmokeFailure(RuntimeError):
    pass


def request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    body: bytes | None = None,
    content_type: str = "application/json",
    timeout: float = 120,
) -> tuple[int, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    if body is not None:
        headers["Content-Type"] = content_type
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read()
        try:
            response_body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            response_body = raw.decode("utf-8", errors="replace")
        return exc.code, response_body
    except (TimeoutError, URLError) as exc:
        raise SmokeFailure(f"{method} {path} failed: {exc}") from exc


def multipart_file(field: str, filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = f"offline-hub-{secrets.token_hex(16)}"
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        "Content-Type: text/plain\r\n\r\n"
    ).encode("utf-8")
    body = prefix + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def require_status(status: int, expected: int, body: Any, label: str) -> Any:
    if status != expected:
        raise SmokeFailure(f"{label}: expected HTTP {expected}, received {status}: {body!r}")
    return body


class Probe:
    def __init__(self, *, base_url: str, phase: str) -> None:
        self.base_url = base_url
        self.phase = phase
        self.checks: list[Check] = []

    def check(self, name: str, operation: Any) -> Any:
        started = time.perf_counter()
        try:
            result, detail = operation()
        except Exception as exc:
            duration = round((time.perf_counter() - started) * 1000, 3)
            self.checks.append(Check(name, False, duration, str(exc)))
            raise
        duration = round((time.perf_counter() - started) * 1000, 3)
        self.checks.append(Check(name, True, duration, detail))
        return result


def health(probe: Probe) -> None:
    def operation() -> tuple[None, str]:
        status, body = request_json(probe.base_url, "GET", "/health")
        require_status(status, 200, body, "health")
        return None, "HTTP 200"

    probe.check("health", operation)


def login(probe: Probe, email: str, password: str) -> str:
    def operation() -> tuple[str, str]:
        status, body = request_json(
            probe.base_url,
            "POST",
            "/api/v1/auth/login",
            payload={"email": email, "password": password},
        )
        require_status(status, 200, body, "login")
        if not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
            raise SmokeFailure("login response omitted access_token")
        return body["access_token"], "access and refresh tokens returned"

    return probe.check("login", operation)


def register(probe: Probe, email: str, password: str) -> None:
    def operation() -> tuple[None, str]:
        status, body = request_json(
            probe.base_url,
            "POST",
            "/api/v1/auth/register",
            payload={"email": email, "password": password},
        )
        require_status(status, 201, body, "register")
        return None, "user created"

    probe.check("register", operation)


def upload(probe: Probe, token: str, marker: str) -> int:
    content = (
        "Offline acceptance record. "
        f"The exact recovery verification code is {marker}. "
        "This fact must remain available after restart and restore.\n"
    ).encode("utf-8")
    body, content_type = multipart_file("file", "wp7.5-acceptance.txt", content)

    def operation() -> tuple[int, str]:
        status, response = request_json(
            probe.base_url,
            "POST",
            "/api/v1/documents",
            token=token,
            body=body,
            content_type=content_type,
        )
        require_status(status, 201, response, "upload")
        if not isinstance(response, dict) or not isinstance(response.get("id"), int):
            raise SmokeFailure("upload response omitted document id")
        return response["id"], f"document_id={response['id']}"

    return probe.check("upload", operation)


def wait_for_ingestion(probe: Probe, token: str, document_id: int, timeout: float) -> None:
    def operation() -> tuple[None, str]:
        deadline = time.monotonic() + timeout
        last: Any = None
        while time.monotonic() < deadline:
            status, body = request_json(
                probe.base_url,
                "GET",
                f"/api/v1/documents/{document_id}",
                token=token,
            )
            require_status(status, 200, body, "document status")
            last = body
            if isinstance(body, dict) and body.get("status") == "ready":
                count = body.get("chunk_count")
                if not isinstance(count, int) or count < 1:
                    raise SmokeFailure("ready document has no chunks")
                return None, f"ready; chunk_count={count}"
            if isinstance(body, dict) and body.get("status") == "failed":
                raise SmokeFailure(f"ingestion failed: {body.get('ingestion_error')}")
            time.sleep(1)
        raise SmokeFailure(f"ingestion timed out; last response={last!r}")

    probe.check("ingestion", operation)


def verify_retrieval(probe: Probe, token: str, document_id: int, marker: str) -> None:
    def operation() -> tuple[None, str]:
        status, body = request_json(
            probe.base_url,
            "POST",
            "/api/v1/documents/search",
            token=token,
            payload={"query": "What is the exact recovery verification code?", "limit": 5},
        )
        require_status(status, 200, body, "document search")
        matches = [
            item
            for item in body
            if isinstance(item, dict)
            and item.get("document_id") == document_id
            and marker in str(item.get("content", ""))
        ] if isinstance(body, list) else []
        if not matches:
            raise SmokeFailure("dense retrieval did not return the seeded marker and document")
        return None, f"matched document_id={document_id}; score={matches[0].get('score')}"

    probe.check("dense_retrieval", operation)


def grounded_generation(probe: Probe, token: str, document_id: int, marker: str) -> int:
    def operation() -> tuple[int, str]:
        status, body = request_json(
            probe.base_url,
            "POST",
            "/api/v1/chat/completions",
            token=token,
            payload={
                "messages": [{
                    "role": "user",
                    "content": "According to the document, what is the exact recovery verification code? Reply with the code.",
                }],
                "use_documents": True,
                "document_ids": [document_id],
                "retrieval_limit": 5,
                "max_tokens": 48,
                "temperature": 0,
            },
            timeout=180,
        )
        require_status(status, 200, body, "grounded generation")
        if not isinstance(body, dict):
            raise SmokeFailure("chat response is not an object")
        choices = body.get("choices")
        answer = ""
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                answer = str(message.get("content", ""))
        sources = body.get("sources")
        matching_sources = [
            source
            for source in sources
            if isinstance(source, dict)
            and source.get("document_id") == document_id
            and marker in str(source.get("content", ""))
        ] if isinstance(sources, list) else []
        conversation_id = body.get("conversation_id")
        if marker not in answer:
            raise SmokeFailure(f"generated answer omitted marker; answer={answer!r}")
        if not matching_sources:
            raise SmokeFailure("generated answer omitted the matching persisted citation")
        if not isinstance(conversation_id, int):
            raise SmokeFailure("generated answer was not persisted as a conversation")
        return conversation_id, f"conversation_id={conversation_id}; grounded marker returned"

    return probe.check("grounded_generation", operation)


def verify_persisted_state(
    probe: Probe,
    token: str,
    document_id: int,
    conversation_id: int,
    marker: str,
) -> None:
    def document_operation() -> tuple[None, str]:
        status, body = request_json(
            probe.base_url,
            "GET",
            f"/api/v1/documents/{document_id}/chunks",
            token=token,
        )
        require_status(status, 200, body, "document chunks")
        if not isinstance(body, list) or not any(marker in str(item.get("content", "")) for item in body):
            raise SmokeFailure("persisted chunks omitted the marker")
        return None, f"document_id={document_id}; marker present"

    def conversation_operation() -> tuple[None, str]:
        status, body = request_json(
            probe.base_url,
            "GET",
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            token=token,
        )
        require_status(status, 200, body, "conversation messages")
        assistant = [item for item in body if isinstance(item, dict) and item.get("role") == "assistant"] if isinstance(body, list) else []
        if not assistant or marker not in str(assistant[-1].get("content", "")):
            raise SmokeFailure("persisted assistant message omitted the marker")
        sources = assistant[-1].get("sources")
        if not isinstance(sources, list) or not any(source.get("document_id") == document_id for source in sources):
            raise SmokeFailure("persisted assistant message omitted its document source")
        return None, f"conversation_id={conversation_id}; assistant source retained"

    probe.check("persisted_document", document_operation)
    probe.check("persisted_conversation", conversation_operation)


def load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokeFailure(f"invalid smoke state: {exc}") from exc
    required = {"email": str, "document_id": int, "conversation_id": int, "marker": str}
    if not isinstance(state, dict) or any(not isinstance(state.get(key), kind) for key, kind in required.items()):
        raise SmokeFailure("smoke state has an invalid shape")
    return state


def write_json(path: Path, payload: dict[str, Any], *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(mode)


def run(args: argparse.Namespace) -> int:
    password = os.environ.get(args.password_env)
    if not password:
        raise SmokeFailure(f"required password environment variable is unset: {args.password_env}")
    state_path = Path(args.state).expanduser().absolute()
    output_path = Path(args.output).expanduser().absolute()
    probe = Probe(base_url=args.base_url, phase=args.phase)
    state: dict[str, Any] | None = None
    error: str | None = None
    started = time.perf_counter()
    try:
        health(probe)
        if args.phase == "seed":
            email = args.email or f"wp7.5-{int(time.time())}@offline.test"
            marker = args.marker
            register(probe, email, password)
            token = login(probe, email, password)
            document_id = upload(probe, token, marker)
            wait_for_ingestion(probe, token, document_id, args.ingestion_timeout)
            verify_retrieval(probe, token, document_id, marker)
            conversation_id = grounded_generation(probe, token, document_id, marker)
            verify_persisted_state(probe, token, document_id, conversation_id, marker)
            state = {
                "email": email,
                "document_id": document_id,
                "conversation_id": conversation_id,
                "marker": marker,
            }
            write_json(state_path, state, mode=0o600)
        else:
            state = load_state(state_path)
            token = login(probe, state["email"], password)
            wait_for_ingestion(probe, token, state["document_id"], args.ingestion_timeout)
            verify_retrieval(probe, token, state["document_id"], state["marker"])
            verify_persisted_state(
                probe,
                token,
                state["document_id"],
                state["conversation_id"],
                state["marker"],
            )
            grounded_generation(probe, token, state["document_id"], state["marker"])
    except Exception as exc:
        error = str(exc)
    report = {
        "report_type": "airgap_application_smoke",
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "phase": args.phase,
        "base_url": args.base_url,
        "passed": error is None and all(check.passed for check in probe.checks),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "checks": [asdict(check) for check in probe.checks],
        "error": error,
        "state_identity": {
            key: state[key]
            for key in ("email", "document_id", "conversation_id", "marker")
        } if state else None,
    }
    write_json(output_path, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("seed", "verify"))
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--state", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--password-env", default="AIRGAP_SMOKE_PASSWORD")
    parser.add_argument("--email")
    parser.add_argument("--marker", default="ORBIT-7429")
    parser.add_argument("--ingestion-timeout", type=float, default=180)
    return parser


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except SmokeFailure as exc:
        print(f"air-gap smoke failed before report creation: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
