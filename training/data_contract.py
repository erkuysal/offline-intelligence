from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from training.foundation import CONFIG_PATH, load_training_config


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
)


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
    reserved_evaluation_datasets: tuple[str, ...]


@dataclass(frozen=True)
class TrainingDataset:
    manifest: TrainingManifest
    examples: tuple[TrainingExample, ...]


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
                {"source_id", "source_uri", "license", "redistribution", "synthetic", "generator"},
                issues,
                record_location,
            )
            source_id = _required_string(record, "source_id", issues, record_location)
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
    if not isinstance(citations_value, list):
        _issue(issues, "citations", "expected_citations must be an array", location)
    else:
        assistant_output = messages[-1]["content"] if messages and messages[-1]["role"] == "assistant" else ""
        seen_citations: set[tuple[str, str]] = set()
        for index, citation in enumerate(citations_value):
            citation_location = f"{location}.expected_citations[{index}]"
            if not isinstance(citation, dict):
                _issue(issues, "citation", "citation must be an object", citation_location)
                continue
            _reject_unknown_fields(
                citation,
                {"source_id", "passage_id"},
                issues,
                citation_location,
            )
            source_id = _required_string(citation, "source_id", issues, citation_location)
            passage_id = citation.get("passage_id", "")
            if not isinstance(passage_id, str):
                _issue(issues, "citation", "passage_id must be a string", citation_location)
                passage_id = ""
            key = (source_id, passage_id)
            if key in seen_citations:
                _issue(issues, "citation", "duplicate expected citation", citation_location)
            seen_citations.add(key)
            if source_id not in source_ids:
                _issue(issues, "citation_source", f"unknown source_id {source_id}", citation_location)
            marker = f"[{source_id}#{passage_id}]" if passage_id else f"[{source_id}]"
            if marker not in assistant_output:
                _issue(
                    issues,
                    "citation_marker",
                    f"assistant output is missing {marker}",
                    citation_location,
                )
            citations.append({"source_id": source_id, **({"passage_id": passage_id} if passage_id else {})})
    if task in {"grounded_answer", "citation_formatting"} and not citations:
        _issue(issues, "citations", f"{task} requires at least one expected citation", location)
    if task == "grounded_refusal" and citations:
        _issue(issues, "citations", "grounded_refusal must not assert source citations", location)

    target_schema = value.get("target_json_schema")
    if task == "json_output":
        if not isinstance(target_schema, dict):
            _issue(issues, "json_target_schema", "json_output requires target_json_schema", location)
        elif messages and messages[-1]["role"] == "assistant":
            try:
                target = json.loads(messages[-1]["content"])
            except json.JSONDecodeError as exc:
                _issue(issues, "json_target", f"assistant output is not valid JSON: {exc}", location)
            else:
                _validate_json_value(target, target_schema, issues, f"{location}.target")
    elif target_schema is not None and not isinstance(target_schema, dict):
        _issue(issues, "json_target_schema", "target_json_schema must be an object", location)

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
        sensitivity=sensitivity,
        template_family=template_family,
        group_key=group_key,
        intended_split=intended_split,
        target_json_schema=target_schema if isinstance(target_schema, dict) else None,
        approval=approval,
    )


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
            reserved_evaluation_datasets=reserved_datasets,
        ),
        examples=tuple(examples),
    )


def build_validation_report(
    manifest_path: Path, *, config_path: Path = CONFIG_PATH
) -> dict[str, Any]:
    try:
        dataset = load_training_dataset(manifest_path, config_path=config_path)
    except TrainingDataError as exc:
        return {
            "schema_version": 1,
            "passed": False,
            "manifest": str(manifest_path),
            "issue_count": len(exc.issues),
            "issues": [
                {"code": issue.code, "message": issue.message, "location": issue.location}
                for issue in exc.issues
            ],
        }
    task_counts = Counter(example.task for example in dataset.examples)
    language_counts = Counter(example.language for example in dataset.examples)
    return {
        "schema_version": 1,
        "passed": True,
        "manifest": str(manifest_path),
        "dataset_id": dataset.manifest.dataset_id,
        "dataset_version": dataset.manifest.dataset_version,
        "examples_sha256": dataset.manifest.examples_sha256,
        "example_count": len(dataset.examples),
        "task_counts": dict(sorted(task_counts.items())),
        "language_counts": dict(sorted(language_counts.items())),
        "issue_count": 0,
        "issues": [],
    }
