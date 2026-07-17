# Phase 5 Training Data Contract Acceptance

Date: 2026-07-15

Status: Work Package 5.1 accepted; Phase 5 subsequently closed with the base-only runtime

## Accepted Scope

- Versioned `TrainingExample` and `TrainingManifest` schemas cover all six planned English/Turkish
  behavior-adaptation tasks.
- Every accepted target has reviewable provenance, redistribution status, copied-source-text state,
  and an independent verified support review.
- Explicit approval is required for synthetic, internal, or redistribution-restricted examples.
- Deterministic validation rejects secrets, credentials, common personal-data patterns, copied
  restricted text, prohibited sources, unverifiable cited targets, invalid roles/citations/JSON
  targets, and Phase 4 evaluation-source leakage.
- The cached pinned Gemma tokenizer and production Jinja template render successfully in the
  `offline-ai-training` environment. The real smoke message renders to 17 tokens, and the validator
  rejects any example above the approved 1,024-token limit.
- Exact duplicate task/message/target content fails validation. Near duplicates are reported by
  stable example IDs and are joined for splitting.
- Group keys, template families, and near-duplicate relationships form indivisible split
  components. Conflicting explicit splits fail; automatic assignments are derived from the pinned
  seed and SHA-256.
- Reports contain task/language/split distributions, sequence-length aggregates, duplicate rates,
  rejection reasons, assignments, and reproducible examples/split/dataset checksums without
  copying training messages or source text.

## Verification Evidence

- Focused schema and semantic contract tests: 17 passed.
- Ruff: passed for the changed validator, tests, and CLI integration.
- Mypy: passed for all five `training` modules.
- Real pinned-tokenizer/template smoke: passed locally with `local_files_only=True`.
- Repeated-manifest test produces identical split assignments, split checksum, and dataset
  checksum.

## Boundaries

- Pattern scanning is a deterministic minimum and does not replace human privacy, license, or
  factual review.
- Near-duplicate similarity is a review signal; linked examples are kept together rather than
  silently deleted.
- No production training dataset is accepted by this record. It accepts the contract and tooling
  through which a future reviewed dataset must pass.
- No adapter training or promotion is authorized by this acceptance record.

Work Package 5.2 is building the four-mode evaluation matrix while dataset curation continues
through this accepted contract.
