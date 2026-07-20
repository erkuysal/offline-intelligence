import json
from pathlib import Path
from types import SimpleNamespace

from scripts.delivery import airgap_smoke as smoke


PASSWORD = "test-only-password"
MARKER = "ORBIT-7429"


def fake_request_json(
    _base_url: str,
    method: str,
    path: str,
    **kwargs: object,
) -> tuple[int, object]:
    if path == "/health":
        return 200, {"status": "ok"}
    if path == "/api/v1/auth/register":
        return 201, {"id": 1}
    if path == "/api/v1/auth/login":
        return 200, {"access_token": "access", "refresh_token": "refresh"}
    if path == "/api/v1/documents" and method == "POST":
        return 201, {"id": 7}
    if path == "/api/v1/documents/7":
        return 200, {"id": 7, "status": "ready", "chunk_count": 1}
    if path == "/api/v1/documents/search":
        return 200, [{"document_id": 7, "content": MARKER, "score": 0.9}]
    if path == "/api/v1/chat/completions":
        return 200, {
            "choices": [{"message": {"content": MARKER}}],
            "sources": [{"document_id": 7, "content": MARKER}],
            "conversation_id": 9,
        }
    if path == "/api/v1/documents/7/chunks":
        return 200, [{"document_id": 7, "content": MARKER}]
    if path == "/api/v1/chat/conversations/9/messages":
        return 200, [
            {
                "role": "assistant",
                "content": MARKER,
                "sources": [{"document_id": 7}],
            }
        ]
    raise AssertionError(f"unexpected request: {method} {path}; kwargs={kwargs}")


def arguments(tmp_path: Path, phase: str) -> SimpleNamespace:
    return SimpleNamespace(
        phase=phase,
        base_url="http://127.0.0.1:3000",
        state=str(tmp_path / "state.json"),
        output=str(tmp_path / f"{phase}.json"),
        password_env="AIRGAP_SMOKE_PASSWORD",
        email="acceptance@offline.test",
        marker=MARKER,
        ingestion_timeout=1,
    )


def test_seed_and_verify_emit_secret_free_machine_reports(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AIRGAP_SMOKE_PASSWORD", PASSWORD)
    monkeypatch.setattr(smoke, "request_json", fake_request_json)

    seed_args = arguments(tmp_path, "seed")
    assert smoke.run(seed_args) == 0
    state_path = Path(seed_args.state)
    assert state_path.stat().st_mode & 0o777 == 0o600

    verify_args = arguments(tmp_path, "verify")
    assert smoke.run(verify_args) == 0

    for report_path in (Path(seed_args.output), Path(verify_args.output)):
        report_text = report_path.read_text(encoding="utf-8")
        report = json.loads(report_text)
        assert report["passed"] is True
        assert PASSWORD not in report_text
        assert all(check["passed"] for check in report["checks"])
