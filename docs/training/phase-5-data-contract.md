# Phase 5 Training Data Contract

Work Package 5.1 accepts JSONL examples only through a versioned manifest. The contract is defined
by `training/schemas/training-example-v1.schema.json` and
`training/schemas/training-manifest-v1.schema.json`; semantic checks live in
`training/data_contract.py`.

## Dataset layout

Keep each reviewable dataset in its own directory:

```text
training/datasets/<dataset-id>/
├── manifest.json
└── examples.jsonl
```

The manifest pins the JSONL SHA-256, base revision, chat-template SHA-256, approved 1,024-token
limit, deterministic split seed, group field, and reserved evaluation datasets. `examples_file`
cannot escape the manifest directory. Split percentages must be positive and total 100.

Every example records a stable ID, task, language, messages, citations, one or more provenance
records, sensitivity, template family, grouping key, and intended split. English and Turkish are
the accepted languages. Supported tasks are grounded answers, grounded refusals, citation
formatting, JSON output, incident reports, and terminology.

## Approval and safety

Explicit approval metadata is mandatory when an example is synthetic, internally sourced, or has
restricted redistribution. A source marked `prohibited` is rejected even when approval metadata is
present. Approval includes an identified reviewer, timezone-qualified review timestamp, and scope;
it is not inferred from the presence of a file in Git.

Validation rejects common private-key, API-token, credential, email-address, US SSN, and Turkish
identity-number patterns. These checks are a deterministic minimum guard, not a substitute for
human source review. Raw restricted documents, secrets, credentials, and personal data must never
be added to a training example or report.

Messages may contain one initial system turn and must then alternate `user`/`assistant`, ending in
an assistant target. Expected citations reference declared provenance and must occur in the target
as `[source_id]` or `[source_id#passage_id]`. Grounded answers and citation-formatting examples need
at least one citation; grounded refusals must not assert one. JSON-output targets must parse and
pass the declared object/array/type, required-field, enum, and additional-property checks.

## Validate

Run validation from the repository root in the application or training environment:

```bash
conda run -n offline-ai python manage.py training-data-validate \
  --manifest training/datasets/<dataset-id>/manifest.json
```

The command returns zero only when the manifest and every example pass. It writes a machine-readable
report under `var/training/` by default, including the dataset identity, checksum, example count,
task distribution, language distribution, and structured rejection issues. Reports must not copy
message content or credentials.

Phase 4 evaluation questions and corpus paths belong in `reserved_evaluation_datasets` and must not
appear in training JSONL. Group-aware split assignment, near-duplicate review, tokenizer rendering,
and length enforcement are subsequent Work Package 5.1 gates.
