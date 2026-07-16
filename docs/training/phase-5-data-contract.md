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
records, an independent support review, sensitivity, template family, grouping key, and intended
split. English and Turkish are the accepted languages. Supported tasks are grounded answers,
grounded refusals, citation formatting, JSON output, incident reports, and terminology.

## Approval and safety

Explicit approval metadata is mandatory when an example is synthetic, internally sourced, or has
restricted redistribution. A source marked `prohibited` is rejected even when approval metadata is
present. Approval includes an identified reviewer, timezone-qualified review timestamp, and scope;
it is not inferred from the presence of a file in Git.

Validation rejects common private-key, API-token, credential, email-address, US SSN, Turkish
identity-number, phone-number, and payment-card patterns. These checks are a deterministic minimum
guard, not a substitute for human source review. Raw restricted documents, secrets, credentials,
and personal data must never be added to a training example or report.

Each provenance record declares `source_text_included`. Copied text is accepted only when its
source has `redistribution: allowed`; copied restricted or prohibited material makes validation
fail. Restricted metadata or behavior derived without copying source text still requires explicit
training approval.

Permission and factual correctness are separate gates. Every target requires `support_review` with
`status: verified`, a reviewer, timezone-qualified timestamp, and the provenance source IDs used to
verify it. Cited sources must be included in that review. Approval alone cannot make an
unverifiable answer eligible for training.

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

Run the command from the pinned training environment because a passing result renders every example
with the cached, pinned Gemma tokenizer and production Jinja template. Validation never downloads a
missing tokenizer as a side effect. The command rejects rendered sequences above the approved
1,024-token limit.

The command returns zero only when the manifest and every example pass. It writes a machine-readable
report under `var/training/` by default, including:

- dataset, examples, and split checksums
- task, language, and assigned-split distributions
- per-example split assignments and aggregate sequence lengths
- exact- and near-duplicate rates, near-duplicate IDs, and similarity scores without message text
- structured rejection issues and rejection-reason counts

Reports must not copy message content, source text, or credentials.

## Deduplication and leakage-safe splits

Exact duplicate task/message/target payloads fail validation even when their example IDs differ.
Near duplicates are reported at a pinned similarity threshold for review. Split components join
examples that share any of the following:

- `group_key`
- `template_family`
- a reported near-duplicate relationship

This keeps paraphrases, bilingual translations, and shared templates in one split. Conflicting
explicit split requests inside one component fail validation. Otherwise, the component's sorted
stable ID, manifest seed, and SHA-256 determine `train`, `validation`, or `held_out`. Re-running
unchanged inputs therefore produces identical assignments, split checksum, and dataset checksum.

Phase 4 evaluation questions and corpus paths belong in `reserved_evaluation_datasets`. Any
training provenance URI that overlaps a reserved identifier fails validation. The promotion corpus
is evidence only and must never become training supervision.
