# Work Package 5.3 — Controlled v2 LoRA Iteration

Date: 2026-07-17

## Objective

The v2 experiment addressed two evidence-backed limitations from the first bounded grid while
holding the selected adapter hyperparameters fixed:

- expand behavioral coverage and development-set size;
- replace the 33-step cosine micro-schedule with a 159-step constant-with-warmup schedule.

Rank `16`, alpha `16`, learning rate `0.0002`, gradient clipping `1.0`, BF16 precision, LoRA target
modules, seed, and deterministic eager attention remained unchanged from the v1 winner.

## Dataset

Dataset `phase5-behavior-training` version `2.0.1` contains 600 authorized public synthetic
examples:

- 420 training;
- 60 validation;
- 120 development held-out;
- 20 held-out cases per task;
- 300 English and 300 Turkish examples;
- five source and prompt layouts;
- production-shaped `[document#passage]` citation markers;
- zero exact or lexical near duplicates at the contract threshold;
- rendered lengths from 79 to 229 tokens.

Dataset checksum:
`61163869be02e998582aa1bc6dfeaeacffcf14278f289aed9605245c66e39a39`.

Protected Phase 4 and Phase 5 evaluation corpora were not used for training, development selection,
or this acceptance decision.

## Methodology corrections

The first v2 attempt revealed two contract defects and is retained only as superseded evidence:

1. Grounded-answer prompts required an exact passage citation but did not expose the passage ID.
2. Training-framework generation stopped on tokenizer EOS (`1`) but not Gemma `<end_of_turn>`
   (`106`), allowing hidden post-turn generation to contaminate decoded answers.

Dataset version `2.0.1` exposes the exact available source marker for grounded answers. Candidate
evaluation now stops on either EOS or `<end_of_turn>`. A Turkish terminology parser defect caused by
the apostrophe in forms such as `UTC'de` was also corrected and regression-tested.

## Training outcome

- Adapter ID: `gemma3-1b-lora-v2-data-schedule-r16-lr0.0002-2cfa8faead45`
- Run fingerprint: `2cfa8faead45` prefix
- Optimizer steps: 159
- Warmup steps: 5
- Final validation loss: `0.000301`
- Peak allocated VRAM: 3,432 MiB
- Training throughput: 311.2 assistant tokens/s
- Wall-clock training time: 150.2 seconds
- Adapter Safetensors SHA-256:
  `3b2672643360d76b7e28f2683f43da5d39b52650c21f9126869c75bdcb6dba87`

The near-zero validation loss is not treated as promotion evidence because validation examples share
behavior families with training data.

## Development held-out outcome

All 120 cases passed:

| Slice | Cases | Token F1 | Language | Task validity |
| --- | ---: | ---: | ---: | ---: |
| Overall | 120 | 1.000 | 1.000 | 1.000 |
| English | 60 | 1.000 | 1.000 | 1.000 |
| Turkish | 60 | 1.000 | 1.000 | 1.000 |
| Grounded answer | 20 | 1.000 | 1.000 | 1.000 |
| Grounded refusal | 20 | 1.000 | 1.000 | 1.000 |
| Citation formatting | 20 | 1.000 | 1.000 | 1.000 |
| JSON output | 20 | 1.000 | 1.000 | 1.000 |
| Incident report | 20 | 1.000 | 1.000 | 1.000 |
| Terminology | 20 | 1.000 | 1.000 | 1.000 |

Held-out report SHA-256:
`1eb99abeb697c4efe13cb12efcd8c9175b6133aeb9236b3ce9828fd7d49b2bc5`.

## Comparison with v1

| Measure | v1 winner | v2.0.1 |
| --- | ---: | ---: |
| Training examples | 84 | 420 |
| Optimizer steps | 33 | 159 |
| Development held-out cases | 24 | 120 |
| Behavior score | 0.668 | 1.000 |
| Task validity | 0.333 | 1.000 |
| Citation formatting validity | 0.000 | 1.000 |
| Incident structure validity | 0.000 | 1.000 |

This is not a single-variable causal comparison: both data coverage and scheduling changed, and the
v2 evaluator corrected two methodological defects. The evidence establishes that the corrected v2
workflow satisfies its development contract; it does not quantify how much improvement came from
each factor.

## Decision

The adapter is `held_out_selection_eligible: true` and may proceed to Work Package 5.4 export and
runtime-integration testing. It remains `promotion_eligible: false`. Promotion still requires the
untouched production behavior matrix, protected Phase 4 regression gates, runtime compatibility,
and performance evidence.
