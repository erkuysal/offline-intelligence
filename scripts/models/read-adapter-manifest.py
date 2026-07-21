#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


def required_string(payload: dict[str, Any], *path: str) -> str:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value if isinstance(value, str) else ""


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    try:
        payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 2
    if not isinstance(payload, dict):
        return 2

    adapter_id = required_string(payload, "adapter_id")
    base_model = required_string(payload, "base_model", "accepted_runtime_model")
    gguf_file = required_string(payload, "runtime", "gguf_file")
    checksum = required_string(payload, "files", gguf_file, "sha256") if gguf_file else ""
    if any("\n" in value or "\r" in value for value in (adapter_id, base_model, gguf_file, checksum)):
        return 2
    print(adapter_id)
    print(base_model)
    print(gguf_file)
    print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
