from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
ENVIRONMENT_PATH = ROOT / "environment.llama-build.yml"
BUILD_SCRIPT = ROOT / "scripts" / "models" / "build-llama-cuda.sh"


def test_llama_cuda_build_inputs_are_pinned() -> None:
    environment = ENVIRONMENT_PATH.read_text(encoding="utf-8")
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "name: offline-ai-llama-build" in environment
    assert "cmake=4.2.3" in environment
    assert "gxx_linux-64=13.4.0" in environment
    assert "nvidia-cuda-nvcc==13.0.88" in environment
    assert "nvidia-cuda-nvrtc==13.0.88" in environment
    assert "nvidia-cuda-runtime==13.0.96" in environment
    assert 'EXPECTED_COMMIT="c198af4dc24f8e0ab8a569a60f931e03a192fd79"' in script
    assert 'CUDA_ARCHITECTURES="${LLAMA_CUDA_ARCHITECTURES:-120a-real}"' in script
    assert "-DGGML_CUDA=ON" in script
    assert "-DCMAKE_BUILD_RPATH=" in script


def test_llama_cuda_build_refuses_the_wrong_environment() -> None:
    environment = os.environ.copy()
    environment.pop("CONDA_DEFAULT_ENV", None)

    result = subprocess.run(
        ["bash", str(BUILD_SCRIPT)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 2
    assert "offline-ai-llama-build" in result.stderr
