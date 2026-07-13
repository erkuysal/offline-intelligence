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
