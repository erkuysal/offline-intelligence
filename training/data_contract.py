from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from training.foundation import CONFIG_PATH, get_hugging_face_token, load_training_config


TASKS = frozenset(
    {
        "grounded_answer",
        "grounded_refusal",
        "citation_formatting",
        "json_output",
        "incident_report",
        "terminology",
    }
)
LANGUAGES = frozenset({"en", "tr"})
SPLITS = frozenset({"auto", "train", "validation", "held_out"})
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
COMMIT_PATTERN = re.compile(r"^[a-f0-9]{40}$")
SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
CITATION_PATTERN = re.compile(
    r"\[([a-z0-9][a-z0-9._-]{2,127})(?:#([a-z0-9][a-z0-9._-]{2,127}))?\]"
)
RUNTIME_CITATION_PATTERN = re.compile(r"\[Source ([1-9][0-9]*)\]")
SENSITIVE_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("hugging_face_token", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)),
    (
        "credential_assignment",
        re.compile(
            r"\b(?:api[_ -]?key|password|passwd|secret|access[_ -]?token)\s*[:=]\s*"
            r"(?!example\b|placeholder\b|redacted\b)[^\s,;]{8,}",
            re.IGNORECASE,
        ),
    ),
    ("email_address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("us_ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("turkish_identity_number", re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)")),
    (
        "phone_number",
        re.compile(
            r"(?<!\d)(?:\+90[\s.-]*|0)5\d{2}[\s.-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)"
        ),
    ),
)
PAYMENT_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
NEAR_DUPLICATE_THRESHOLD = 0.85
PROTECTED_EVALUATION_DATASETS = (
    "evaluation/datasets/dense-baseline-v1.jsonl",
    "evaluation/datasets/phase-5-behavior-v1.jsonl",
)
TokenCounter = Callable[[Sequence[Mapping[str, str]]], int]


class TrainingDataError(ValueError):
    """Raised when a training manifest or example violates the data contract."""

    def __init__(self, issues: Sequence[ValidationIssue]):
        self.issues = tuple(issues)
        summary = "; ".join(issue.format() for issue in self.issues[:5])
        if len(self.issues) > 5:
            summary += f"; and {len(self.issues) - 5} more issue(s)"
        super().__init__(summary)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    location: str

    def format(self) -> str:
        return f"{self.location}: {self.code}: {self.message}"


@dataclass(frozen=True)
class TrainingExample:
    example_id: str
    task: str
    language: str
    messages: tuple[Mapping[str, str], ...]
    expected_citations: tuple[Mapping[str, str], ...]
    provenance: tuple[Mapping[str, Any], ...]
    support_review: Mapping[str, Any]
    sensitivity: str
    template_family: str
    group_key: str
    intended_split: str
    target_json_schema: Mapping[str, Any] | None
    approval: Mapping[str, str] | None


@dataclass(frozen=True)
class TrainingManifest:
    dataset_id: str
    dataset_version: str
    examples_path: Path
    examples_sha256: str
    split_seed: int
    split_percentages: tuple[int, int, int]
    max_sequence_length: int
    reserved_evaluation_datasets: tuple[str, ...]


@dataclass(frozen=True)
class TrainingDataset:
    manifest: TrainingManifest
    examples: tuple[TrainingExample, ...]


@dataclass(frozen=True)
class DatasetAnalysis:
    assignments: Mapping[str, str]
    split_checksum: str
    dataset_checksum: str
    exact_duplicate_rate: float
    near_duplicates: tuple[Mapping[str, Any], ...]
    sequence_lengths: Mapping[str, int]


def _issue(issues: list[ValidationIssue], code: str, message: str, location: str) -> None:
    issues.append(ValidationIssue(code=code, message=message, location=location))


def _reject_unknown_fields(
    value: Mapping[str, Any],
    allowed: set[str],
    issues: list[ValidationIssue],
    location: str,
) -> None:
    for field in sorted(value.keys() - allowed):
        _issue(issues, "unknown_field", f"unexpected field {field}", location)


def _read_object(path: Path, issues: list[ValidationIssue]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        _issue(issues, "file_error", str(exc), str(path))
        return None
    except json.JSONDecodeError as exc:
        _issue(issues, "invalid_json", str(exc), str(path))
        return None
    if not isinstance(value, dict):
        _issue(issues, "invalid_type", "expected a JSON object", str(path))
        return None
    return value


def _required_string(
    value: Mapping[str, Any], field: str, issues: list[ValidationIssue], location: str
) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate.strip():
        _issue(issues, "required_string", f"{field} must be a non-empty string", location)
        return ""
    return candidate


def _validate_approval(value: object, issues: list[ValidationIssue], location: str) -> None:
    if not isinstance(value, dict):
        _issue(issues, "approval_required", "explicit approval metadata is required", location)
        return
    _reject_unknown_fields(
        value,
        {"status", "reviewer", "reviewed_at", "scope"},
        issues,
        location,
    )
    if value.get("status") != "approved":
        _issue(issues, "approval_status", "approval.status must be approved", location)
    _required_string(value, "reviewer", issues, location)
    reviewed_at = _required_string(value, "reviewed_at", issues, location)
    if reviewed_at:
        try:
            parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone is required")
        except ValueError:
            _issue(
                issues,
                "approval_timestamp",
                "approval.reviewed_at must be an ISO-8601 date-time with timezone",
                location,
            )
    if value.get("scope") not in {"training", "training-and-redistribution"}:
        _issue(issues, "approval_scope", "approval.scope is invalid", location)


def _validate_review_timestamp(
    value: Mapping[str, Any], issues: list[ValidationIssue], location: str
) -> None:
    reviewed_at = _required_string(value, "reviewed_at", issues, location)
    if not reviewed_at:
        return
    try:
        parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone is required")
    except ValueError:
        _issue(
            issues,
            "support_review_timestamp",
            "support_review.reviewed_at must be an ISO-8601 date-time with timezone",
            location,
        )


def _validate_support_review(
    value: object,
    source_ids: set[str],
    cited_source_ids: set[str],
    issues: list[ValidationIssue],
    location: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _issue(
            issues,
            "support_review_required",
            "a verified factual-support review is required",
            location,
        )
        return {}
    _reject_unknown_fields(
        value,
        {"status", "reviewer", "reviewed_at", "source_ids"},
        issues,
        location,
    )
    if value.get("status") != "verified":
        _issue(issues, "support_review_status", "support_review.status must be verified", location)
    _required_string(value, "reviewer", issues, location)
    _validate_review_timestamp(value, issues, location)
    reviewed_sources = value.get("source_ids")
    if (
        not isinstance(reviewed_sources, list)
        or not reviewed_sources
        or not all(isinstance(item, str) and item for item in reviewed_sources)
        or len(set(reviewed_sources)) != len(reviewed_sources)
    ):
        _issue(
            issues,
            "support_review_sources",
            "support_review.source_ids must contain unique source identifiers",
            location,
        )
        return value
    unknown = sorted(set(reviewed_sources) - source_ids)
    if unknown:
        _issue(
            issues,
            "support_review_sources",
            f"support review references unknown sources: {', '.join(unknown)}",
            location,
        )
    unsupported_citations = sorted(cited_source_ids - set(reviewed_sources))
    if unsupported_citations:
        _issue(
            issues,
            "unverified_target",
            f"cited targets lack support review: {', '.join(unsupported_citations)}",
            location,
        )
    return value


def _validate_messages(
    value: object, issues: list[ValidationIssue], location: str
) -> tuple[Mapping[str, str], ...]:
    if not isinstance(value, list) or len(value) < 2:
        _issue(issues, "messages", "messages must contain at least user and assistant turns", location)
        return ()
    normalized: list[Mapping[str, str]] = []
    roles: list[str] = []
    for index, message in enumerate(value):
        item_location = f"{location}.messages[{index}]"
        if not isinstance(message, dict):
            _issue(issues, "message_type", "message must be an object", item_location)
            continue
        _reject_unknown_fields(message, {"role", "content"}, issues, item_location)
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"}:
            _issue(issues, "message_role", f"unsupported role {role!r}", item_location)
            continue
        if not isinstance(content, str) or not content.strip():
            _issue(issues, "message_content", "content must be a non-empty string", item_location)
            continue
        if len(content) > 65_536:
            _issue(issues, "message_content", "content exceeds 65,536 characters", item_location)
        for name, pattern in SENSITIVE_PATTERNS:
            if pattern.search(content):
                _issue(
                    issues,
                    "sensitive_content",
                    f"content matches forbidden {name} pattern",
                    item_location,
                )
        for match in PAYMENT_CARD_CANDIDATE.finditer(content):
            digits = [int(character) for character in match.group() if character.isdigit()]
            checksum = 0
            parity = len(digits) % 2
            for digit_index, digit in enumerate(digits):
                candidate = digit * 2 if digit_index % 2 == parity else digit
                checksum += candidate - 9 if candidate > 9 else candidate
            if checksum % 10 == 0:
                _issue(
                    issues,
                    "sensitive_content",
                    "content matches forbidden payment_card_number pattern",
                    item_location,
                )
        roles.append(role)
        normalized.append({"role": role, "content": content})

    if roles:
        system_positions = [index for index, role in enumerate(roles) if role == "system"]
        if system_positions not in ([], [0]):
            _issue(issues, "role_order", "system is allowed only as the first turn", location)
        dialogue = roles[1:] if roles[0] == "system" else roles
        expected = ["user" if index % 2 == 0 else "assistant" for index in range(len(dialogue))]
        if dialogue != expected or not dialogue or dialogue[-1] != "assistant":
            _issue(
                issues,
                "role_order",
                "turns must alternate user/assistant and end with assistant",
                location,
            )
    return tuple(normalized)


def _validate_json_value(
    value: object,
    schema: Mapping[str, Any],
    issues: list[ValidationIssue],
    location: str,
) -> None:
    expected_type = schema.get("type")
    type_matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    if isinstance(expected_type, str) and expected_type in type_matches and not type_matches[expected_type]:
        _issue(issues, "json_target_schema", f"expected JSON type {expected_type}", location)
        return
    if "enum" in schema and value not in schema["enum"]:
        _issue(issues, "json_target_schema", "value is not in the schema enum", location)
    if isinstance(value, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for field in required:
                if field not in value:
                    _issue(issues, "json_target_schema", f"missing required field {field}", location)
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for field, child_schema in properties.items():
                if field in value and isinstance(child_schema, dict):
                    _validate_json_value(value[field], child_schema, issues, f"{location}.{field}")
            if schema.get("additionalProperties") is False:
                for field in value.keys() - properties.keys():
                    _issue(
                        issues,
                        "json_target_schema",
                        f"unexpected field {field}",
                        location,
                    )
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            _validate_json_value(item, schema["items"], issues, f"{location}[{index}]")


def _validate_target_schema_definition(
    schema: Mapping[str, Any], issues: list[ValidationIssue], location: str
) -> None:
    allowed = {"type", "enum", "required", "additionalProperties", "properties", "items"}
    _reject_unknown_fields(schema, allowed, issues, location)
    schema_type = schema.get("type")
    if schema_type not in {"object", "array", "string", "number", "integer", "boolean", "null"}:
        _issue(issues, "json_target_schema", "schema type is missing or unsupported", location)
    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum):
        _issue(issues, "json_target_schema", "schema enum must be a non-empty array", location)
    required = schema.get("required")
    if required is not None and (
        schema_type != "object"
        or not isinstance(required, list)
        or not all(isinstance(field, str) and field for field in required)
        or len(set(required)) != len(required)
    ):
        _issue(
            issues,
            "json_target_schema",
            "schema required must contain unique object property names",
            location,
        )
    additional_properties = schema.get("additionalProperties")
    if additional_properties is not None and not isinstance(additional_properties, bool):
        _issue(
            issues,
            "json_target_schema",
            "schema additionalProperties must be boolean",
            location,
        )
    properties = schema.get("properties")
    if properties is not None:
        if schema_type != "object" or not isinstance(properties, dict):
            _issue(issues, "json_target_schema", "schema properties require an object", location)
        else:
            for field, child in properties.items():
                if not isinstance(field, str) or not field or not isinstance(child, dict):
                    _issue(
                        issues,
                        "json_target_schema",
                        "schema properties must map names to schema objects",
                        location,
                    )
                    continue
                _validate_target_schema_definition(child, issues, f"{location}.properties.{field}")
    items = schema.get("items")
    if items is not None:
        if schema_type != "array" or not isinstance(items, dict):
            _issue(issues, "json_target_schema", "schema items require an array", location)
        else:
            _validate_target_schema_definition(items, issues, f"{location}.items")


def _validate_example(
    value: Mapping[str, Any], issues: list[ValidationIssue], location: str
) -> TrainingExample | None:
    starting_issue_count = len(issues)
    _reject_unknown_fields(
        value,
        {
            "schema_version",
            "example_id",
            "task",
            "language",
            "messages",
            "expected_citations",
            "target_json_schema",
            "provenance",
            "support_review",
            "sensitivity",
            "approval",
            "template_family",
            "group_key",
            "intended_split",
        },
        issues,
        location,
    )
    if value.get("schema_version") != "1.0":
        _issue(issues, "schema_version", "schema_version must be 1.0", location)
    example_id = _required_string(value, "example_id", issues, location)
    if example_id and not ID_PATTERN.fullmatch(example_id):
        _issue(issues, "example_id", "example_id has an invalid format", location)
    task = _required_string(value, "task", issues, location)
    if task not in TASKS:
        _issue(issues, "task", f"unsupported task {task!r}", location)
    language = _required_string(value, "language", issues, location)
    if language not in LANGUAGES:
        _issue(issues, "language", f"unsupported language {language!r}", location)
    messages = _validate_messages(value.get("messages"), issues, location)

    provenance_value = value.get("provenance")
    provenance: list[Mapping[str, Any]] = []
    source_ids: set[str] = set()
    approval_required = value.get("sensitivity") != "public"
    if not isinstance(provenance_value, list) or not provenance_value:
        _issue(issues, "provenance", "at least one provenance record is required", location)
    else:
        for index, record in enumerate(provenance_value):
            record_location = f"{location}.provenance[{index}]"
            if not isinstance(record, dict):
                _issue(issues, "provenance", "provenance record must be an object", record_location)
                continue
            _reject_unknown_fields(
                record,
                {
                    "source_id",
                    "source_uri",
                    "license",
                    "redistribution",
                    "synthetic",
                    "source_text_included",
                    "generator",
                },
                issues,
                record_location,
            )
            source_id = _required_string(record, "source_id", issues, record_location)
            if source_id and not ID_PATTERN.fullmatch(source_id):
                _issue(issues, "provenance", "source_id has an invalid format", record_location)
            _required_string(record, "source_uri", issues, record_location)
            _required_string(record, "license", issues, record_location)
            if source_id in source_ids:
                _issue(issues, "provenance", f"duplicate source_id {source_id}", record_location)
            source_ids.add(source_id)
            redistribution = record.get("redistribution")
            if redistribution not in {"allowed", "restricted", "prohibited"}:
                _issue(issues, "redistribution", "invalid redistribution status", record_location)
            if redistribution == "prohibited":
                _issue(
                    issues,
                    "redistribution_prohibited",
                    "prohibited source material cannot be used for training",
                    record_location,
                )
            if redistribution == "restricted":
                approval_required = True
            source_text_included = record.get("source_text_included")
            if not isinstance(source_text_included, bool):
                _issue(
                    issues,
                    "source_text_included",
                    "source_text_included must be boolean",
                    record_location,
                )
            elif source_text_included and redistribution != "allowed":
                _issue(
                    issues,
                    "restricted_source_text",
                    "restricted or prohibited source text cannot be copied into training data",
                    record_location,
                )
            synthetic = record.get("synthetic")
            if not isinstance(synthetic, bool):
                _issue(issues, "synthetic", "synthetic must be boolean", record_location)
            elif synthetic:
                approval_required = True
                _required_string(record, "generator", issues, record_location)
            provenance.append(record)

    sensitivity = _required_string(value, "sensitivity", issues, location)
    if sensitivity not in {"public", "internal-approved"}:
        _issue(issues, "sensitivity", "sensitivity must be public or internal-approved", location)
    approval_value = value.get("approval")
    if approval_required:
        _validate_approval(approval_value, issues, f"{location}.approval")

    citations_value = value.get("expected_citations")
    citations: list[Mapping[str, str]] = []
    assistant_output = (
        messages[-1]["content"] if messages and messages[-1]["role"] == "assistant" else ""
    )
    if not isinstance(citations_value, list):
        _issue(issues, "citations", "expected_citations must be an array", location)
    else:
        seen_citations: set[tuple[str, str, str]] = set()
        for index, citation in enumerate(citations_value):
            citation_location = f"{location}.expected_citations[{index}]"
            if not isinstance(citation, dict):
                _issue(issues, "citation", "citation must be an object", citation_location)
                continue
            _reject_unknown_fields(
                citation,
                {"source_id", "passage_id", "runtime_label"},
                issues,
                citation_location,
            )
            source_id = _required_string(citation, "source_id", issues, citation_location)
            if source_id and not ID_PATTERN.fullmatch(source_id):
                _issue(issues, "citation_syntax", "source_id has an invalid format", citation_location)
            passage_id = citation.get("passage_id", "")
            if not isinstance(passage_id, str):
                _issue(issues, "citation", "passage_id must be a string", citation_location)
                passage_id = ""
            elif passage_id and not ID_PATTERN.fullmatch(passage_id):
                _issue(
                    issues,
                    "citation_syntax",
                    "passage_id has an invalid format",
                    citation_location,
                )
            runtime_label = citation.get("runtime_label", "")
            if not isinstance(runtime_label, str):
                _issue(issues, "citation", "runtime_label must be a string", citation_location)
                runtime_label = ""
            elif runtime_label and not re.fullmatch(r"\[Source [1-9][0-9]*\]", runtime_label):
                _issue(
                    issues,
                    "citation_syntax",
                    "runtime_label must use exact [Source N] syntax",
                    citation_location,
                )
            key = (source_id, passage_id, runtime_label)
            if key in seen_citations:
                _issue(issues, "citation", "duplicate expected citation", citation_location)
            seen_citations.add(key)
            if source_id not in source_ids:
                _issue(issues, "citation_source", f"unknown source_id {source_id}", citation_location)
            marker = runtime_label or (
                f"[{source_id}#{passage_id}]" if passage_id else f"[{source_id}]"
            )
            if marker not in assistant_output:
                _issue(
                    issues,
                    "citation_marker",
                    f"assistant output is missing {marker}",
                    citation_location,
                )
            citations.append(
                {
                    "source_id": source_id,
                    **({"passage_id": passage_id} if passage_id else {}),
                    **({"runtime_label": runtime_label} if runtime_label else {}),
                }
            )
    if task in {"grounded_answer", "citation_formatting"} and not citations:
        _issue(issues, "citations", f"{task} requires at least one expected citation", location)
    if task == "grounded_refusal" and citations:
        _issue(issues, "citations", "grounded_refusal must not assert source citations", location)
    declared_citations = {
        (citation["source_id"], citation.get("passage_id", "")) for citation in citations
    }
    declared_runtime_labels = {
        citation["runtime_label"] for citation in citations if citation.get("runtime_label")
    }
    rendered_citations = {
        (match.group(1), match.group(2) or "")
        for match in CITATION_PATTERN.finditer(assistant_output)
    }
    for source_id, passage_id in sorted(rendered_citations - declared_citations):
        marker = f"[{source_id}#{passage_id}]" if passage_id else f"[{source_id}]"
        _issue(
            issues,
            "undeclared_citation",
            f"assistant output contains undeclared citation {marker}",
            location,
        )
    rendered_runtime_labels = {
        match.group(0) for match in RUNTIME_CITATION_PATTERN.finditer(assistant_output)
    }
    for marker in sorted(rendered_runtime_labels - declared_runtime_labels):
        _issue(
            issues,
            "undeclared_citation",
            f"assistant output contains undeclared citation {marker}",
            location,
        )

    support_review = _validate_support_review(
        value.get("support_review"),
        source_ids,
        {citation["source_id"] for citation in citations},
        issues,
        f"{location}.support_review",
    )

    target_schema = value.get("target_json_schema")
    if task == "json_output":
        if not isinstance(target_schema, dict):
            _issue(issues, "json_target_schema", "json_output requires target_json_schema", location)
        elif messages and messages[-1]["role"] == "assistant":
            _validate_target_schema_definition(target_schema, issues, f"{location}.target_json_schema")
            try:
                target = json.loads(messages[-1]["content"])
            except json.JSONDecodeError as exc:
                _issue(issues, "json_target", f"assistant output is not valid JSON: {exc}", location)
            else:
                _validate_json_value(target, target_schema, issues, f"{location}.target")
    elif target_schema is not None:
        if not isinstance(target_schema, dict):
            _issue(issues, "json_target_schema", "target_json_schema must be an object", location)
        else:
            _validate_target_schema_definition(target_schema, issues, f"{location}.target_json_schema")

    template_family = _required_string(value, "template_family", issues, location)
    group_key = _required_string(value, "group_key", issues, location)
    for field, candidate in (("template_family", template_family), ("group_key", group_key)):
        if candidate and not ID_PATTERN.fullmatch(candidate):
            _issue(issues, field, f"{field} has an invalid format", location)
    intended_split = _required_string(value, "intended_split", issues, location)
    if intended_split not in SPLITS:
        _issue(issues, "intended_split", "intended_split is invalid", location)

    if len(issues) != starting_issue_count:
        return None
    approval = approval_value if isinstance(approval_value, dict) else None
    return TrainingExample(
        example_id=example_id,
        task=task,
        language=language,
        messages=messages,
        expected_citations=tuple(citations),
        provenance=tuple(provenance),
        support_review=support_review,
        sensitivity=sensitivity,
        template_family=template_family,
        group_key=group_key,
        intended_split=intended_split,
        target_json_schema=target_schema if isinstance(target_schema, dict) else None,
        approval=approval,
    )


def _canonical_example_payload(example: TrainingExample) -> dict[str, Any]:
    return {
        "task": example.task,
        "language": example.language,
        "messages": list(example.messages),
        "expected_citations": list(example.expected_citations),
        "target_json_schema": example.target_json_schema,
    }


def _exact_example_fingerprint(example: TrainingExample) -> str:
    encoded = json.dumps(
        _canonical_example_payload(example),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _normalized_example_tokens(example: TrainingExample) -> tuple[str, ...]:
    text = " ".join(message["content"] for message in example.messages)
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return tuple(re.findall(r"\w+", normalized, flags=re.UNICODE))


def _similarity_features(tokens: Sequence[str]) -> frozenset[str]:
    if len(tokens) < 3:
        return frozenset(tokens)
    return frozenset("\u241f".join(tokens[index : index + 3]) for index in range(len(tokens) - 2))


def _near_duplicate_pairs(
    examples: Sequence[TrainingExample],
) -> tuple[Mapping[str, Any], ...]:
    features = [_similarity_features(_normalized_example_tokens(example)) for example in examples]
    postings: dict[str, list[int]] = {}
    for index, example_features in enumerate(features):
        for feature in example_features:
            postings.setdefault(feature, []).append(index)
    candidates: set[tuple[int, int]] = set()
    for indexes in postings.values():
        for left_position, left in enumerate(indexes):
            for right in indexes[left_position + 1 :]:
                candidates.add((left, right))

    pairs: list[Mapping[str, Any]] = []
    for left, right in sorted(candidates):
        union = features[left] | features[right]
        if not union:
            continue
        score = len(features[left] & features[right]) / len(union)
        if score >= NEAR_DUPLICATE_THRESHOLD:
            pairs.append(
                {
                    "left_example_id": examples[left].example_id,
                    "right_example_id": examples[right].example_id,
                    "similarity": round(score, 6),
                }
            )
    return tuple(pairs)


class _DisjointGroups:
    def __init__(self, size: int):
        self.parents = list(range(size))

    def find(self, item: int) -> int:
        while self.parents[item] != item:
            self.parents[item] = self.parents[self.parents[item]]
            item = self.parents[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parents[max(left_root, right_root)] = min(left_root, right_root)


def _deterministic_split(
    component_key: str, seed: int, percentages: tuple[int, int, int]
) -> str:
    digest = hashlib.sha256(f"{seed}:{component_key}".encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    train_percent, validation_percent, _ = percentages
    if bucket < train_percent:
        return "train"
    if bucket < train_percent + validation_percent:
        return "validation"
    return "held_out"


def analyze_training_dataset(
    dataset: TrainingDataset,
    *,
    token_counter: TokenCounter,
) -> DatasetAnalysis:
    issues: list[ValidationIssue] = []
    examples = dataset.examples
    sequence_lengths: dict[str, int] = {}
    for example in examples:
        try:
            token_count = token_counter(example.messages)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            _issue(
                issues,
                "template_render",
                f"pinned template/tokenizer rendering failed: {exc}",
                example.example_id,
            )
            continue
        if not isinstance(token_count, int) or isinstance(token_count, bool) or token_count <= 0:
            _issue(
                issues,
                "token_count",
                "token counter must return a positive integer",
                example.example_id,
            )
            continue
        sequence_lengths[example.example_id] = token_count
        if token_count > dataset.manifest.max_sequence_length:
            _issue(
                issues,
                "sequence_too_long",
                f"rendered sequence has {token_count} tokens; maximum is "
                f"{dataset.manifest.max_sequence_length}",
                example.example_id,
            )

    near_duplicates = _near_duplicate_pairs(examples)
    groups = _DisjointGroups(len(examples))
    first_group_key: dict[str, int] = {}
    first_template_family: dict[str, int] = {}
    indexes_by_id = {example.example_id: index for index, example in enumerate(examples)}
    for index, example in enumerate(examples):
        if example.group_key in first_group_key:
            groups.union(index, first_group_key[example.group_key])
        else:
            first_group_key[example.group_key] = index
        if example.template_family in first_template_family:
            groups.union(index, first_template_family[example.template_family])
        else:
            first_template_family[example.template_family] = index
    for pair in near_duplicates:
        groups.union(
            indexes_by_id[str(pair["left_example_id"])],
            indexes_by_id[str(pair["right_example_id"])],
        )

    components: dict[int, list[TrainingExample]] = {}
    for index, example in enumerate(examples):
        components.setdefault(groups.find(index), []).append(example)

    assignments: dict[str, str] = {}
    for members in components.values():
        explicit_splits = {
            example.intended_split for example in members if example.intended_split != "auto"
        }
        component_ids = sorted(example.example_id for example in members)
        if len(explicit_splits) > 1:
            _issue(
                issues,
                "split_conflict",
                "linked group/template/duplicate examples request different explicit splits",
                ",".join(component_ids),
            )
            continue
        assigned_split = (
            next(iter(explicit_splits))
            if explicit_splits
            else _deterministic_split(
                f"{dataset.manifest.dataset_id}:{dataset.manifest.dataset_version}:"
                f"{component_ids[0]}",
                dataset.manifest.split_seed,
                dataset.manifest.split_percentages,
            )
        )
        for example in members:
            assignments[example.example_id] = assigned_split

    if issues:
        raise TrainingDataError(issues)

    ordered_assignments = dict(sorted(assignments.items()))
    assignment_bytes = json.dumps(
        ordered_assignments, sort_keys=True, separators=(",", ":")
    ).encode()
    split_checksum = hashlib.sha256(assignment_bytes).hexdigest()
    dataset_identity = {
        "dataset_id": dataset.manifest.dataset_id,
        "dataset_version": dataset.manifest.dataset_version,
        "examples_sha256": dataset.manifest.examples_sha256,
        "split_seed": dataset.manifest.split_seed,
        "split_percentages": dataset.manifest.split_percentages,
        "split_checksum": split_checksum,
    }
    dataset_checksum = hashlib.sha256(
        json.dumps(dataset_identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return DatasetAnalysis(
        assignments=ordered_assignments,
        split_checksum=split_checksum,
        dataset_checksum=dataset_checksum,
        exact_duplicate_rate=0.0,
        near_duplicates=near_duplicates,
        sequence_lengths=dict(sorted(sequence_lengths.items())),
    )


def build_hugging_face_token_counter(
    config: Mapping[str, Any],
    *,
    template_path: Path,
    local_files_only: bool = True,
) -> TokenCounter:
    try:
        from transformers import AutoTokenizer  # type: ignore[import-not-found]
    except (ImportError, OSError) as exc:
        raise ValueError("Transformers is required for tokenizer validation") from exc
    try:
        template = template_path.read_text(encoding="utf-8")
        template_sha256 = hashlib.sha256(template.encode()).hexdigest()
        if template_sha256 != config["prompt_contract"]["chat_template_sha256"]:
            raise ValueError("chat template SHA-256 does not match the pinned contract")
        tokenizer = AutoTokenizer.from_pretrained(
            config["base_model"]["repo_id"],
            revision=config["base_model"]["revision"],
            token=get_hugging_face_token(),
            local_files_only=local_files_only,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError(f"could not load the pinned tokenizer/template: {exc}") from exc
    if tokenizer.vocab_size != config["prompt_contract"]["tokenizer_vocab_size"]:
        raise ValueError("tokenizer vocabulary size does not match the pinned contract")
    for token, expected_id in config["prompt_contract"]["control_token_ids"].items():
        if tokenizer.convert_tokens_to_ids(token) != expected_id:
            raise ValueError(f"control token {token} does not match the pinned contract")
    tokenizer.chat_template = template

    def count_tokens(messages: Sequence[Mapping[str, str]]) -> int:
        encoded = tokenizer.apply_chat_template(
            list(messages),
            tokenize=True,
            add_generation_prompt=False,
        )
        if isinstance(encoded, Mapping):
            encoded = encoded.get("input_ids")
        if not isinstance(encoded, list):
            raise ValueError("tokenizer returned an unexpected encoded sequence")
        return len(encoded)

    return count_tokens


def load_training_dataset(
    manifest_path: Path, *, config_path: Path = CONFIG_PATH
) -> TrainingDataset:
    issues: list[ValidationIssue] = []
    manifest_payload = _read_object(manifest_path, issues)
    if manifest_payload is None:
        raise TrainingDataError(issues)
    config = load_training_config(config_path)
    location = str(manifest_path)

    _reject_unknown_fields(
        manifest_payload,
        {
            "schema_version",
            "dataset_id",
            "dataset_version",
            "description",
            "examples_file",
            "examples_sha256",
            "example_schema",
            "template_contract",
            "split_policy",
            "reserved_evaluation_datasets",
        },
        issues,
        location,
    )

    if manifest_payload.get("schema_version") != "1.0":
        _issue(issues, "schema_version", "schema_version must be 1.0", location)
    dataset_id = _required_string(manifest_payload, "dataset_id", issues, location)
    if dataset_id and not ID_PATTERN.fullmatch(dataset_id):
        _issue(issues, "dataset_id", "dataset_id has an invalid format", location)
    dataset_version = _required_string(manifest_payload, "dataset_version", issues, location)
    if dataset_version and not SEMVER_PATTERN.fullmatch(dataset_version):
        _issue(issues, "dataset_version", "dataset_version must be semantic versioning", location)
    _required_string(manifest_payload, "description", issues, location)
    if manifest_payload.get("example_schema") != "../schemas/training-example-v1.schema.json":
        _issue(issues, "example_schema", "unexpected training example schema", location)

    examples_file = _required_string(manifest_payload, "examples_file", issues, location)
    examples_path = (manifest_path.parent / examples_file).resolve()
    manifest_directory = manifest_path.parent.resolve()
    if examples_path.parent != manifest_directory or examples_path.suffix != ".jsonl":
        _issue(
            issues,
            "examples_path",
            "examples_file must name a JSONL file in the manifest directory",
            location,
        )
    expected_sha256 = _required_string(manifest_payload, "examples_sha256", issues, location)
    if expected_sha256 and not SHA256_PATTERN.fullmatch(expected_sha256):
        _issue(issues, "examples_sha256", "examples_sha256 must be lowercase SHA-256", location)

    template = manifest_payload.get("template_contract")
    max_sequence_length = -1
    if not isinstance(template, dict):
        _issue(issues, "template_contract", "template_contract must be an object", location)
    else:
        _reject_unknown_fields(
            template,
            {"base_model_revision", "chat_template_sha256", "max_sequence_length"},
            issues,
            location,
        )
        revision = _required_string(template, "base_model_revision", issues, location)
        template_sha = _required_string(template, "chat_template_sha256", issues, location)
        max_length = template.get("max_sequence_length")
        if not COMMIT_PATTERN.fullmatch(revision):
            _issue(issues, "base_model_revision", "invalid base model revision", location)
        if revision != config["base_model"]["revision"]:
            _issue(issues, "base_model_revision", "revision does not match training config", location)
        if not SHA256_PATTERN.fullmatch(template_sha):
            _issue(issues, "chat_template_sha256", "invalid template SHA-256", location)
        if template_sha != config["prompt_contract"]["chat_template_sha256"]:
            _issue(issues, "chat_template_sha256", "template does not match training config", location)
        if max_length != config["training"]["approved_max_sequence_length"]:
            _issue(issues, "max_sequence_length", "length does not match approved config", location)
        elif isinstance(max_length, int) and not isinstance(max_length, bool):
            max_sequence_length = max_length

    split_policy = manifest_payload.get("split_policy")
    split_seed = -1
    percentages = (0, 0, 0)
    if not isinstance(split_policy, dict):
        _issue(issues, "split_policy", "split_policy must be an object", location)
    else:
        _reject_unknown_fields(
            split_policy,
            {
                "seed",
                "train_percent",
                "validation_percent",
                "held_out_percent",
                "group_field",
            },
            issues,
            location,
        )
        seed_value = split_policy.get("seed")
        percentage_values = tuple(
            split_policy.get(field)
            for field in ("train_percent", "validation_percent", "held_out_percent")
        )
        if not isinstance(seed_value, int) or isinstance(seed_value, bool) or seed_value < 0:
            _issue(issues, "split_seed", "split seed must be a non-negative integer", location)
        else:
            split_seed = seed_value
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in percentage_values):
            _issue(issues, "split_percentages", "split percentages must be integers", location)
        else:
            train_percent, validation_percent, held_out_percent = percentage_values
            assert isinstance(train_percent, int)
            assert isinstance(validation_percent, int)
            assert isinstance(held_out_percent, int)
            percentages = (
                train_percent,
                validation_percent,
                held_out_percent,
            )
            if any(value <= 0 for value in percentages) or sum(percentages) != 100:
                _issue(issues, "split_percentages", "split percentages must be positive and total 100", location)
        if split_policy.get("group_field") != "group_key":
            _issue(issues, "split_group", "split grouping field must be group_key", location)

    reserved = manifest_payload.get("reserved_evaluation_datasets")
    reserved_datasets: tuple[str, ...] = ()
    if (
        not isinstance(reserved, list)
        or not reserved
        or not all(isinstance(item, str) and item for item in reserved)
        or len(set(reserved)) != len(reserved)
    ):
        _issue(
            issues,
            "reserved_evaluation_datasets",
            "at least one unique reserved evaluation dataset is required",
            location,
        )
    else:
        reserved_datasets = tuple(reserved)

    examples: list[TrainingExample] = []
    raw_examples: bytes | None = None
    try:
        raw_examples = examples_path.read_bytes()
    except OSError as exc:
        _issue(issues, "examples_file", str(exc), str(examples_path))
    if raw_examples is not None:
        actual_sha256 = hashlib.sha256(raw_examples).hexdigest()
        if actual_sha256 != expected_sha256:
            _issue(
                issues,
                "examples_sha256_mismatch",
                f"expected {expected_sha256}; found {actual_sha256}",
                str(examples_path),
            )
        try:
            decoded_examples = raw_examples.decode("utf-8")
        except UnicodeDecodeError as exc:
            _issue(issues, "invalid_encoding", str(exc), str(examples_path))
            decoded_examples = ""
        for line_number, line in enumerate(decoded_examples.splitlines(), start=1):
            if not line.strip():
                continue
            line_location = f"{examples_path}:{line_number}"
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                _issue(issues, "invalid_json", str(exc), line_location)
                continue
            if not isinstance(payload, dict):
                _issue(issues, "invalid_type", "example must be a JSON object", line_location)
                continue
            example = _validate_example(payload, issues, line_location)
            if example is not None:
                examples.append(example)
    if not examples:
        _issue(issues, "empty_dataset", "dataset must contain at least one valid example", location)
    duplicate_ids = [item for item, count in Counter(example.example_id for example in examples).items() if count > 1]
    for example_id in duplicate_ids:
        _issue(issues, "duplicate_example_id", f"duplicate example_id {example_id}", location)

    fingerprints: dict[str, list[str]] = {}
    for example in examples:
        fingerprints.setdefault(_exact_example_fingerprint(example), []).append(example.example_id)
    for example_ids in fingerprints.values():
        if len(example_ids) > 1:
            _issue(
                issues,
                "exact_duplicate",
                f"examples have duplicate task/messages/target content: {', '.join(sorted(example_ids))}",
                location,
            )

    reserved_markers = tuple(
        item.replace("\\", "/").removeprefix("./").casefold()
        for item in (*reserved_datasets, *PROTECTED_EVALUATION_DATASETS)
    )
    for example in examples:
        for provenance in example.provenance:
            source_uri = str(provenance.get("source_uri", ""))
            normalized_uri = source_uri.replace("\\", "/").removeprefix("./").casefold()
            for marker in reserved_markers:
                if marker and marker in normalized_uri:
                    _issue(
                        issues,
                        "reserved_evaluation_leakage",
                        f"source URI overlaps reserved evaluation dataset {marker}",
                        example.example_id,
                    )

    if issues:
        raise TrainingDataError(issues)
    return TrainingDataset(
        manifest=TrainingManifest(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            examples_path=examples_path,
            examples_sha256=expected_sha256,
            split_seed=split_seed,
            split_percentages=percentages,
            max_sequence_length=max_sequence_length,
            reserved_evaluation_datasets=reserved_datasets,
        ),
        examples=tuple(examples),
    )


def build_validation_report(
    manifest_path: Path,
    *,
    config_path: Path = CONFIG_PATH,
    token_counter: TokenCounter | None = None,
    local_files_only: bool = True,
) -> dict[str, Any]:
    def failed_report(issues: Sequence[ValidationIssue]) -> dict[str, Any]:
        reason_counts = Counter(issue.code for issue in issues)
        return {
            "schema_version": 1,
            "report_type": "dataset_validation",
            "passed": False,
            "manifest": str(manifest_path),
            "issue_count": len(issues),
            "rejection_reason_counts": dict(sorted(reason_counts.items())),
            "issues": [
                {"code": issue.code, "message": issue.message, "location": issue.location}
                for issue in issues
            ],
        }

    try:
        dataset = load_training_dataset(manifest_path, config_path=config_path)
    except TrainingDataError as exc:
        return failed_report(exc.issues)

    if token_counter is None:
        try:
            config = load_training_config(config_path)
            configured_template_path = Path(config["prompt_contract"]["chat_template_path"])
            token_counter = build_hugging_face_token_counter(
                config,
                template_path=configured_template_path,
                local_files_only=local_files_only,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return failed_report(
                (
                    ValidationIssue(
                        code="tokenizer_unavailable",
                        message=str(exc),
                        location=str(config_path),
                    ),
                )
            )
    try:
        analysis = analyze_training_dataset(dataset, token_counter=token_counter)
    except TrainingDataError as exc:
        return failed_report(exc.issues)

    task_counts = Counter(example.task for example in dataset.examples)
    language_counts = Counter(example.language for example in dataset.examples)
    split_counts = Counter(analysis.assignments.values())
    sequence_lengths = sorted(analysis.sequence_lengths.values())
    near_duplicate_example_ids = {
        str(pair[field])
        for pair in analysis.near_duplicates
        for field in ("left_example_id", "right_example_id")
    }
    return {
        "schema_version": 1,
        "report_type": "dataset_validation",
        "passed": True,
        "manifest": str(manifest_path),
        "dataset_id": dataset.manifest.dataset_id,
        "dataset_version": dataset.manifest.dataset_version,
        "examples_sha256": dataset.manifest.examples_sha256,
        "dataset_checksum": analysis.dataset_checksum,
        "split_checksum": analysis.split_checksum,
        "example_count": len(dataset.examples),
        "task_counts": dict(sorted(task_counts.items())),
        "language_counts": dict(sorted(language_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "split_assignments": analysis.assignments,
        "sequence_lengths": {
            "minimum": min(sequence_lengths),
            "maximum": max(sequence_lengths),
            "mean": round(sum(sequence_lengths) / len(sequence_lengths), 3),
            "approved_maximum": dataset.manifest.max_sequence_length,
        },
        "duplicates": {
            "exact_pair_count": 0,
            "exact_duplicate_rate": analysis.exact_duplicate_rate,
            "near_pair_count": len(analysis.near_duplicates),
            "near_duplicate_example_rate": round(
                len(near_duplicate_example_ids) / len(dataset.examples), 6
            ),
            "near_pairs": list(analysis.near_duplicates),
            "near_threshold": NEAR_DUPLICATE_THRESHOLD,
        },
        "issue_count": 0,
        "rejection_reason_counts": {},
        "issues": [],
    }
