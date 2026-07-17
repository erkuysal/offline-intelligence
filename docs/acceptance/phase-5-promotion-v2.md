# Phase 5 v2 Adapter Promotion Decision

Date: 2026-07-17

Work package: 5.5

Adapter: `gemma3-1b-lora-v2-data-schedule-r16-lr0.0002-2cfa8faead45`
Decision: **rejected; base-only runtime remains the default**

## Evidence boundary

The deployed GGUF adapter and accepted Q4_K_M base were evaluated through the same pinned llama.cpp
build, prompt implementation, generation settings, dense retrieval implementation, EmbeddingGemma
runtime, PostgreSQL corpus preparation, and datasets. The behavior corpus contained 12 untouched
bilingual cases across all six Phase 5 tasks. The protected Phase 4 regression corpus contained 40
cases. Adapter activation was verified through `/lora-adapters`; all model servers were stopped.

The evidence index is `var/training/wp5.5/evidence-index.json`, SHA-256
`2362e785c481cb56204f6bab44a14b9f7b038ebb2baaeae38b14141e05589063`, and records
`promotion_passed: false`. The strict matrix SHA-256 is
`9cf0ec58b8a1d1696d28e338732f5f470bf7e1359b58829dd39a69fb718e5cd8`.

## Behavior gates

| Adapter + RAG behavior | Actual | Required | Result |
| --- | ---: | ---: | --- |
| Language adherence | 0.8333 | 1.0000 | Fail |
| Citation-format validity | 0.8000 | 1.0000 | Fail |
| JSON-schema validity | 0.0000 | 1.0000 | Fail |
| Incident-report structure | 0.5000 | 1.0000 | Fail |
| Terminology consistency | 0.5000 | 1.0000 | Fail |
| Supported refusal | 1.0000 | 1.0000 | Pass |

English adapter+RAG quality was materially stronger than Turkish: fact coverage was `0.7333`
versus `0.3000`, faithfulness `0.8000` versus `0.2000`, and hallucination `0.2000` versus `0.8000`.
The aggregate therefore did not hide the language-specific regression.

## Protected regression gates

| Metric | Fresh base + RAG | Adapter + RAG | Promotion target | Result |
| --- | ---: | ---: | ---: | --- |
| Parse success | 1.0000 | 1.0000 | 1.0000 | Pass |
| Expected fact coverage | 0.6719 | 0.3906 | >= 0.7500 | Fail |
| Citation accuracy | 0.6562 | 0.4062 | >= 0.7500 | Fail |
| Citation coverage | 0.7188 | 0.5938 | >= 0.8000 | Fail |
| Answer faithfulness | 0.6562 | 0.4062 | >= 0.7500 | Fail |
| Hallucination rate | 0.3438 | 0.5938 | <= 0.2500 | Fail |
| Refusal accuracy | 1.0000 | 1.0000 | 1.0000 | Pass |
| Restricted-fact leaks | 0 | 0 | 0 | Pass |
| Mean TTFT | 36.6 ms | 50.2 ms | <= base + 20% | Fail |
| P95 TTFT | 43.8 ms | 58.2 ms | <= base + 20% | Fail |
| Mean end-to-end | 108.6 ms | 134.1 ms | <= base + 20% | Fail |
| Throughput | 188.1 tok/s | 152.4 tok/s | >= base - 20% | Pass, narrowly |

The fresh base+RAG run passed every protected Phase 4 floor. The rejection is therefore caused by
the adapter, not an unhealthy base or retrieval stack.

## Methodological corrections

The production evaluator initially failed to recognize the trained phrase “I do not have enough
information.” Equivalent English and Turkish forms already accepted by the training evaluator were
added to the production refusal parser and covered by tests. Refusal accuracy then rose from an
invalid `0.0000` to `1.0000`; all remaining failures persisted.

The evidence index also incorrectly required a passing matrix. It now indexes either decision and
records `promotion_passed`, allowing a rejected candidate to retain the same immutable audit trail
as an accepted one. Neither correction weakened a model-quality threshold.

## Decision

The v2 adapter is rejected and must not become the default. Its exported package is retained as
reproducible negative evidence. A future iteration must align training with the actual production
RAG message boundary, `[Source N]` citation grammar, production JSON schemas, incident headings,
natural-answer regression behavior, and bilingual prompts before retraining.
