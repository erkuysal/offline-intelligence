# Work Package 5.3 — Bounded LoRA Training Evidence

Date: 2026-07-16

## Dataset gate

The project-owner-authorized `phase5-behavior-training` `1.0.0` corpus contains 120 public synthetic
examples. It is balanced across English/Turkish and all six tasks. The deterministic split contains
84 training, 12 validation, and 24 untouched held-out examples. Validation found zero exact or near
duplicates; rendered lengths range from 82 to 193 tokens. The dataset checksum is
`05db4375a5c0e8382eb16f1e8039e80313f8b1765b7a7bd69968a852f2a83730`.

The corpus does not reuse either protected dataset:

- `evaluation/datasets/dense-baseline-v1.jsonl`
- `evaluation/datasets/phase-5-behavior-v1.jsonl`

## Methodology correction

The first attempted real run exposed PyTorch's non-deterministic memory-efficient attention
backward kernel. It was interrupted and retained only as failed evidence. Accepted candidates pin
eager attention, treat nondeterministic kernels as hard errors, and trim each batch to its rendered
length. The failed attempt is never eligible for selection.

## Bounded grid

All accepted runs used BF16, three epochs, 33 optimizer steps, micro-batch 1, accumulation 8, AdamW,
cosine scheduling, the pinned Gemma revision, and assistant-only loss masking.

| Rank | Learning rate | Final validation loss | Held-out behavior | Task validity | Result |
| ---: | ---: | ---: | ---: | ---: | --- |
| 8 | 0.0001 | 1.4030 | 0.592 | 0.250 | Fail |
| 8 | 0.0002 | 0.9315 | 0.626 | 0.292 | Fail |
| 16 | 0.0001 | 1.4137 | 0.610 | 0.250 | Fail |
| 16 | 0.0002 | 0.9362 | 0.668 | 0.333 | Selected, not promotable |

Candidate selection uses the fewest held-out threshold failures and then the highest held-out
behavior score. Training loss is explicitly excluded. The selected adapter is
`gemma3-1b-lora-v1-r16-lr0.0002-86d9eadb1eab`, but `promotion_eligible` is false.

## Decision

Work Package 5.3's training machinery and bounded experiment are accepted as executed. No adapter
is accepted for Work Package 5.4 export. The next training iteration must address the genuine
held-out failures—especially required citation markers and bilingual incident sections—without
weakening evaluator thresholds or contaminating protected evaluation corpora.
