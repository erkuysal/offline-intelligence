from __future__ import annotations

import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from training.adapter_export import validate_peft_export_compatibility
from training.foundation import load_training_config
from training.trainer import TrainingRunError


ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config/training/gemma3-1b-lora-v2.json"


class FakeSafeTensorFile:
    def __init__(self, keys: list[str]):
        self._keys = keys

    def __enter__(self) -> FakeSafeTensorFile:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def keys(self) -> list[str]:
        return self._keys


def write_adapter(
    path: Path, monkeypatch: pytest.MonkeyPatch, *, embedding: bool = False
) -> None:
    path.mkdir()
    config = load_training_config(CONFIG_PATH)
    lora = config["training"]["lora"]
    (path / "adapter_config.json").write_text(
        json.dumps(
            {
                "base_model_name_or_path": config["base_model"]["repo_id"],
                "peft_type": "LORA",
                "task_type": "CAUSAL_LM",
                "r": lora["rank"],
                "lora_alpha": lora["alpha"],
                "target_modules": lora["target_modules"],
                "modules_to_save": None,
                "trainable_token_indices": None,
                "bias": "none",
                "use_dora": False,
                "use_rslora": False,
            }
        ),
        encoding="utf-8",
    )
    prefix = (
        "base_model.model.model.embed_tokens"
        if embedding
        else "base_model.model.model.layers.0.self_attn.q_proj"
    )
    keys = [f"{prefix}.lora_A.weight", f"{prefix}.lora_B.weight"]
    (path / "adapter_model.safetensors").write_bytes(b"test-only-safetensors-placeholder")
    module = ModuleType("safetensors")
    module.safe_open = lambda *_args, **_kwargs: FakeSafeTensorFile(keys)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "safetensors", module)


def test_peft_export_accepts_paired_supported_lora_tensors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = tmp_path / "adapter"
    write_adapter(adapter, monkeypatch)

    report = validate_peft_export_compatibility(load_training_config(CONFIG_PATH), adapter)

    assert report["tensor_count"] == 2
    assert report["tensor_pair_count"] == 1
    assert report["checks"]["base_model"] is True


def test_peft_export_rejects_added_token_embeddings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = tmp_path / "adapter"
    write_adapter(adapter, monkeypatch, embedding=True)

    with pytest.raises(TrainingRunError, match="embeddings"):
        validate_peft_export_compatibility(load_training_config(CONFIG_PATH), adapter)
