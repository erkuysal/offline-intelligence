# ADR 0005: Language-Neutral PostgreSQL Lexical Search

## Status

Accepted for the Phase 4 lexical baseline on 14 July 2026.

## Decision

Use PostgreSQL full-text search with the `simple` text-search configuration for the initial English,
Turkish, and mixed-language corpus. Store generated `tsvector` columns for document filenames and
chunk content, with a GIN index on each column. Parse user input with parameterized
`websearch_to_tsquery`.

Normalize identifier separators (`-`, `_`, `.`, `/`, and `:`) to spaces in both indexed text and
queries. This makes forms such as `API-503`, `OPS_RUNBOOK`, and versioned filenames resolve to the
same lexemes while leaving SQL construction parameterized.

Convert ordinary unstructured query terms to `OR`-joined websearch input so natural-language
questions do not require every question word to appear in a passage. Preserve explicitly quoted or
boolean websearch syntax. `ts_rank_cd` still rewards candidates matching more query terms.

Rank each matching chunk with the greater of its content and filename `ts_rank_cd` scores. Preserve
the raw rank and expose `rank / (1 + rank)` as the candidate's bounded normalized score. Apply
readiness, owner/read-permission, and optional document filters inside the SQL query before ordering
and limiting results.

## Rationale

The `simple` configuration lowercases and tokenizes without language-specific stemming or stop-word
removal. This gives deterministic behavior for English, Turkish, mixed passages, identifiers,
acronyms, and filenames without guessing a document language that the current schema does not store.
It also avoids applying English stemming rules to Turkish text or vice versa.

Generated vectors keep indexed text synchronized with source columns. `websearch_to_tsquery` accepts
phrases, exclusions, and user-facing search syntax without constructing SQL or `tsquery` fragments
from untrusted input.

## Consequences

- Exact lexical forms, phrases, identifiers, and filenames are the initial strength of this strategy.
- Turkish and English morphological variants are not conflated by stemming.
- Filename matches require a join to the indexed document vector.
- The lexical evaluator must be measured against the accepted dense corpus before hybrid fusion is
  accepted.
- Language detection or per-language configurations can be reconsidered only with evaluation evidence.
