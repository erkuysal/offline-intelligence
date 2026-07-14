# Phase 4 Context Selection Acceptance

Date: 2026-07-14
Status: Accepted
Dataset: `dense-baseline` `1.0.0`
Strategy measured: PostgreSQL lexical retrieval

## Accepted Behavior

The runtime context selector removes exact duplicate passage text, trims already-covered character
intervals from overlapping chunks in the same document, and applies both a total context budget and
a per-document budget. Candidate order remains stable, and citation numbers are assigned only after
selection so removed candidates cannot leave gaps in source numbering.

Selection diagnostics are stored with retrieval runs without adding passage text. They include input
and selected counts, exact duplicates removed, overlapping characters removed, considered and unique
characters, selected characters, and the unique-context ratio. Prometheus operation metrics expose
context selection and exact/overlap deduplication outcomes.

## Evaluation Evidence

The formal 20-document, 40-question English/Turkish corpus was rerun at retrieval limit 5 using the
same context selector and the configured 12,000-character total and 6,000-character per-document
budgets.

```text
Recall@5: 0.969
Precision@5: 0.441
Mean Reciprocal Rank: 0.969
Hit rate: 0.969
No-result accuracy: 0.500
Authorization leaks: 0
Mean unique-context ratio: 1.000
Mean relevant-context retention: 1.000
Mean retrieval latency: 1.8 ms
P95 retrieval latency: 5.6 ms
```

The corpus produces one non-overlapping chunk per document, so its unique-context ratio is expected
to be 1.000. Synthetic selector tests separately cover exact duplicates, adjacent overlap trimming,
budget truncation, stable citation numbering, and a duplicate-heavy case with a measured 0.500
unique-context ratio. Relevant context was fully retained in both the formal run and duplicate-heavy
test.

## Decision

Context selection is accepted for the chat retrieval pipeline. The formal metrics protect relevant
passages from selection regressions, while runtime diagnostics make duplicate-heavy production cases
observable without enabling raw query or passage persistence.
