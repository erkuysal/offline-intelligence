import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]


def run_startup_script(script: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / "models" / script)],
        cwd=ROOT,
        env={**os.environ, "APP_ENV_FILE": "/dev/null", **environment},
        capture_output=True,
        check=False,
        text=True,
    )


def test_llm_startup_reports_missing_local_model(tmp_path: Path) -> None:
    missing_model = tmp_path / "missing-chat.gguf"

    result = run_startup_script(
        "start-llm.sh",
        {
            "LLM_BASE_URL": "http://127.0.0.1:1/v1",
            "LLAMA_CPP_BIN": "/bin/true",
            "LLAMA_MODEL_PATH": str(missing_model),
            "LLAMA_PID_FILE": str(tmp_path / "llm.pid"),
        },
    )

    assert result.returncode == 2
    assert f"LLM model file is missing or unreadable: {missing_model}" in result.stderr
    assert "Set LLAMA_MODEL_PATH" in result.stderr


def test_llm_startup_reports_missing_adapter(tmp_path: Path) -> None:
    missing_adapter = tmp_path / "missing-adapter.gguf"
    result = run_startup_script(
        "start-llm.sh",
        {
            "LLM_BASE_URL": "http://127.0.0.1:1/v1",
            "LLAMA_CPP_BIN": "/bin/true",
            "LLAMA_MODEL_REPO": "test/base",
            "LLM_ADAPTER_PATH": str(missing_adapter),
            "LLM_ADAPTER_ID": "adapter-v1",
            "LLM_ADAPTER_SHA256": "0" * 64,
            "LLAMA_PID_FILE": str(tmp_path / "llm.pid"),
        },
    )

    assert result.returncode == 2
    assert f"LLM adapter file is missing or unreadable: {missing_adapter}" in result.stderr


def test_llm_startup_rejects_corrupt_adapter(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter.gguf"
    adapter.write_bytes(b"corrupt")
    result = run_startup_script(
        "start-llm.sh",
        {
            "LLM_BASE_URL": "http://127.0.0.1:1/v1",
            "LLAMA_CPP_BIN": "/bin/true",
            "LLAMA_MODEL_REPO": "test/base",
            "LLM_ADAPTER_PATH": str(adapter),
            "LLM_ADAPTER_ID": "adapter-v1",
            "LLM_ADAPTER_SHA256": "0" * 64,
            "LLAMA_PID_FILE": str(tmp_path / "llm.pid"),
        },
    )

    assert result.returncode == 2
    assert "LLM adapter checksum mismatch" in result.stderr


def test_llm_startup_rejects_incompatible_adapter_manifest(tmp_path: Path) -> None:
    import hashlib
    import json

    adapter = tmp_path / "adapter.gguf"
    adapter.write_bytes(b"valid-test-adapter")
    checksum = hashlib.sha256(adapter.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "adapter_id": "adapter-v1",
                "base_model": {"accepted_runtime_model": "different/base"},
                "runtime": {"gguf_file": adapter.name},
                "files": {adapter.name: {"sha256": checksum}},
            }
        ),
        encoding="utf-8",
    )
    result = run_startup_script(
        "start-llm.sh",
        {
            "LLM_BASE_URL": "http://127.0.0.1:1/v1",
            "LLAMA_CPP_BIN": "/bin/true",
            "LLAMA_MODEL_REPO": "test/base",
            "LLM_ADAPTER_PATH": str(adapter),
            "LLM_ADAPTER_MANIFEST": str(manifest),
            "LLM_ADAPTER_ID": "adapter-v1",
            "LLM_ADAPTER_SHA256": checksum,
            "LLAMA_PID_FILE": str(tmp_path / "llm.pid"),
        },
    )

    assert result.returncode == 2
    assert "adapter is incompatible with configured base model" in result.stderr


def test_llm_startup_accepts_manifest_verified_adapter(tmp_path: Path) -> None:
    import hashlib
    import json

    adapter = tmp_path / "adapter.gguf"
    adapter.write_bytes(b"valid-test-adapter")
    checksum = hashlib.sha256(adapter.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "adapter_id": "adapter-v1",
                "base_model": {"accepted_runtime_model": "test/base"},
                "runtime": {"gguf_file": adapter.name},
                "files": {adapter.name: {"sha256": checksum}},
            }
        ),
        encoding="utf-8",
    )
    result = run_startup_script(
        "start-llm.sh",
        {
            "LLM_BASE_URL": "http://127.0.0.1:1/v1",
            "LLAMA_CPP_BIN": "/bin/true",
            "LLAMA_MODEL_REPO": "test/base",
            "LLM_ADAPTER_PATH": str(adapter),
            "LLM_ADAPTER_MANIFEST": str(manifest),
            "LLM_ADAPTER_SCALE": "0.75",
            "LLM_ADAPTER_ID": "adapter-v1",
            "LLM_ADAPTER_SHA256": checksum,
            "LLAMA_PID_FILE": str(tmp_path / "llm.pid"),
        },
    )

    assert result.returncode == 0
    assert f"Adapter: adapter-v1 ({checksum})" in result.stdout
    assert "Adapter scale: 0.75" in result.stdout


def test_llm_startup_default_remains_adapter_free(tmp_path: Path) -> None:
    result = run_startup_script(
        "start-llm.sh",
        {
            "LLM_BASE_URL": "http://127.0.0.1:1/v1",
            "LLAMA_CPP_BIN": "/bin/true",
            "LLAMA_MODEL_REPO": "test/base",
            "LLAMA_PID_FILE": str(tmp_path / "llm.pid"),
        },
    )

    assert result.returncode == 0
    assert "Adapter: disabled" in result.stdout


def test_embedding_startup_reports_missing_local_model(tmp_path: Path) -> None:
    missing_model = tmp_path / "missing-embedding.gguf"

    result = run_startup_script(
        "start-embedding.sh",
        {
            "EMBEDDING_BASE_URL": "http://127.0.0.1:1/v1",
            "EMBEDDING_LLAMA_CPP_BIN": "/bin/true",
            "EMBEDDING_SERVER_MODEL_PATH": str(missing_model),
            "EMBEDDING_SERVER_PID_FILE": str(tmp_path / "embedding.pid"),
        },
    )

    assert result.returncode == 2
    assert f"Embedding model file is missing or unreadable: {missing_model}" in result.stderr
    assert "Set EMBEDDING_SERVER_MODEL_PATH" in result.stderr
