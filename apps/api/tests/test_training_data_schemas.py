from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = ROOT / "training" / "schemas"


def load_schema(name: str) -> dict[str, Any]:
    payload = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_training_example_schema_is_closed_versioned_and_bilingual() -> None:
    schema = load_schema("training-example-v1.schema.json")

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"] == {"const": "1.0"}
    assert schema["properties"]["language"]["enum"] == ["en", "tr"]
    assert set(schema["properties"]["task"]["enum"]) == {
        "grounded_answer",
        "grounded_refusal",
        "citation_formatting",
        "json_output",
        "incident_report",
        "terminology",
    }


def test_training_example_schema_requires_provenance_and_grouping() -> None:
    schema = load_schema("training-example-v1.schema.json")

    assert {
        "example_id",
        "messages",
        "expected_citations",
        "provenance",
        "sensitivity",
        "template_family",
        "group_key",
        "intended_split",
    } <= set(schema["required"])
    assert schema["properties"]["provenance"]["type"] == "array"
    provenance = schema["$defs"]["provenance"]
    assert {"source_id", "source_uri", "license", "redistribution", "synthetic"} <= set(
        provenance["required"]
    )
    assert set(provenance["properties"]["redistribution"]["enum"]) == {
        "allowed",
        "restricted",
        "prohibited",
    }


def test_training_example_schema_gates_json_synthetic_and_internal_data() -> None:
    schema = load_schema("training-example-v1.schema.json")
    encoded_conditions = json.dumps(schema["allOf"], sort_keys=True)

    assert "target_json_schema" in encoded_conditions
    assert '"synthetic": {"const": true}' in encoded_conditions
    assert '"sensitivity": {"const": "internal-approved"}' in encoded_conditions
    assert '"required": ["approval"]' in encoded_conditions


def test_training_manifest_schema_pins_examples_template_splits_and_reservations() -> None:
    schema = load_schema("training-manifest-v1.schema.json")

    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"] == {"const": "1.0"}
    assert {
        "examples_file",
        "examples_sha256",
        "example_schema",
        "template_contract",
        "split_policy",
        "reserved_evaluation_datasets",
    } <= set(schema["required"])
    assert schema["properties"]["template_contract"]["properties"][
        "max_sequence_length"
    ]["maximum"] == 1024
    assert schema["properties"]["split_policy"]["properties"]["group_field"] == {
        "const": "group_key"
    }
    assert schema["properties"]["reserved_evaluation_datasets"]["minItems"] == 1
