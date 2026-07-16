# Fine-Tuning Post-Mortem: Under-Adaptation of Behavioral Contracts

Date: 2026-07-16

## Executive Summary

The primary limitation of this run was the under-adaptation of exact behavioral contracts rather
than a lack of general language or factual comprehension. While the best adapter understood the
task content, it failed to reliably execute strict output syntax. The model learned what to say,
but not exactly how to format it.

The complete bounded `2 × 2` experiment selected rank `16` at learning rate `0.0002` using held-out
behavior evidence. Its behavior score reached `0.668`, but task validity remained `0.333`.
Consequently, the adapter is explicitly marked `promotion_eligible: false` and must not advance to
export or runtime integration.

## 1. Data Exposure and Optimization Constraints

### 1.1 Training exposure was too small

The training split contained only 84 examples: seven per task/language combination and 14 per task
overall. Across the run, the model processed approximately 9,048 supervised assistant tokens and
performed just 33 optimizer updates. This was enough to move behavior measurably, but insufficient
to override the model's strong pretrained formatting tendencies.

| Outcome | Best result |
| --- | ---: |
| Mean token F1 | 0.670 |
| Task validity | 0.333 |

Research directions:

- Determine the minimum example threshold per behavior contract.
- Oversample empirically difficult behaviors.
- Compare additional epochs against additional unique examples.
- Measure whether syntax compliance benefits from curriculum ordering.

### 1.2 The optimization schedule was too short

With 84 examples, gradient accumulation of 8, and three epochs, the run performed:

```text
ceil(84 / 8) × 3 = 33 optimizer steps
```

A configured warmup ratio of `0.03` resulted in:

```text
floor(33 × 0.03) = 0 warmup steps
```

Cosine decay was therefore compressed into only 33 steps, leaving the final epoch at a substantially
reduced learning rate. Higher learning rates demonstrably improved performance:

| Configuration | Final validation loss | Behavior score |
| --- | ---: | ---: |
| Rank 8, `0.0001` | 1.4030 | 0.592 |
| Rank 8, `0.0002` | 0.9315 | 0.626 |
| Rank 16, `0.0001` | 1.4137 | 0.610 |
| Rank 16, `0.0002` | 0.9362 | 0.668 |

Research directions:

- Use constant or constant-with-warmup scheduling for micro-runs.
- Establish step-based bounds, such as 100–300 steps, rather than relying only on epochs.
- Set an explicit minimum number of warmup steps.
- Log the effective learning rate at every update.

### 1.3 Aggressive gradient clipping may have suppressed updates

Reported pre-clipping gradient norms ranged from approximately `2.2` to `8.9`, while the configured
maximum was `1.0`. Nearly every optimizer update was therefore clipped. This guaranteed numerical
stability—there were no non-finite gradients—but may have reduced effective update magnitude,
particularly during early steps when adaptation pressure was strongest.

This is a technical hypothesis, not a proven cause. It must be isolated through a controlled
comparison.

Research directions:

- Analyze LoRA gradient-norm and parameter-update distributions.
- Compare maximum norms of `1.0`, `2.0`, and `5.0` under the same seed.
- Record post-clipping as well as pre-clipping norms.
- Explore adaptive gradient clipping.

### 1.4 Rank comparison was confounded by fixed alpha

Both rank 8 and rank 16 used `alpha = 16`. Standard LoRA scaling is approximately:

```text
scale = alpha / rank
```

This produced different scaling factors:

```text
rank 8  → scale 2.0
rank 16 → scale 1.0
```

The rank-16 adapter therefore had twice the capacity but half the per-rank scaling multiplier.
Despite this, rank 16 yielded better held-out behavior at `0.0002`. A clean capacity comparison
requires proportional alpha scaling.

Research directions:

- Compare rank 8/alpha 16 with rank 16/alpha 32.
- Test rank-stabilized LoRA.
- Record LoRA update norms by target module.
- Study rank, alpha, and learning-rate interactions factorially.

## 2. Task-Specific Interference and Failures

### 2.1 Citation identifiers resisted exact copying

The model successfully extracted factual answers—grounded-answer token F1 reached `0.704`—but exact
citation validity remained `0.000`. Identifiers such as:

```text
[train-en-grounded-answer-atlas#facts]
```

are long, punctuation-heavy, unique per example, and likely fragmented into many tokenizer tokens.
Rather than copying them exactly, some outputs regressed to generic Markdown citation habits or
external-looking links.

Research directions:

- Analyze tokenizer fragmentation of production `[document#passage]` identifiers.
- Train with identifiers that match production chunk IDs exactly.
- Test shorter, stable identifiers before increasing complexity.
- Add malformed and multiple-citation examples.
- Investigate pointer-copy weighting or constrained decoding.

### 2.2 Incident reports and JSON interfered as structured-output tasks

The small multitask dataset contained both JSON and incident-report supervision. The model learned a
broad notion of structured output but did not reliably isolate the requested schemas. Incident
outputs degraded into generic Markdown, JSON reports, verbose summaries, or short responses missing
required headings.

Best incident results:

| Metric | Result |
| --- | ---: |
| Token F1 | 0.263 |
| Structure validity | 0.000 |

Research directions:

- Introduce explicit task-control tokens or stronger task labels.
- Add negative examples showing that JSON is incorrect for incident reports.
- Apply curriculum training: syntax-specific stages before mixed supervised fine-tuning.
- Train concise reports and record generation truncation explicitly.

### 2.3 JSON compliance remained brittle

The rank-16/high-learning-rate candidate achieved strong JSON token F1 (`0.930`) but only `0.500`
schema validity. The generated data was often semantically correct, while strict compliance failed
because of Markdown code fences, altered field names or enums, and extra or missing fields.

Research directions:

- Contrast valid raw JSON with invalid fenced JSON during training.
- Increase field-name, enum, and schema variation.
- Measure syntax, schema, and semantic validity separately.
- Consider grammar- or schema-constrained decoding at runtime.

### 2.4 Turkish adaptation lagged behind English

Turkish semantic overlap was slightly higher, while exact behavioral compliance was substantially
lower:

| Slice | Token F1 | Task validity |
| --- | ---: | ---: |
| English | 0.659 | 0.500 |
| Turkish | 0.681 | 0.167 |

The model understood Turkish content but did not reproduce Turkish formatting contracts as
reliably. A possible explanation is stronger English formatting priors, but that remains a
hypothesis rather than a measured cause.

Research directions:

- Oversample Turkish format-sensitive examples.
- Analyze tokenizer fragmentation of Turkish headings and terminology.
- Use difficulty-weighted sampling rather than count-only balance.
- Investigate bilingual curriculum stages or language-conditioned adapters.

## 3. Data Diversity and Evaluation Limitations

### 3.1 Conceptual template diversity was deceptively low

The deterministic deduplicator reported zero near duplicates because it uses normalized token
trigrams and a similarity threshold of `0.85`. However, changing service names, times, owners, and
terms concealed repeated structural templates:

```text
source facts → question → constrained answer
```

The dataset was lexically diverse but conceptually repetitive.

Research directions:

- Add embedding-based semantic deduplication.
- Measure template entropy or structural fingerprints.
- Introduce varied prompt layouts and source formats.
- Add multi-turn, adversarial, and malformed-input examples.

### 3.2 The held-out set was statistically noisy

The held-out split contained 24 cases: four per task and two per task/language combination. A single
successful case therefore changed a task-validity score by `0.25`. This was adequate for a strict
engineering rejection gate, but lacked the statistical power to compare small candidate differences
reliably.

Research directions:

- Expand to 20–30 held-out examples per task.
- Separate development data from the final untouched promotion corpus.
- Report bootstrap confidence intervals.
- Avoid repeated tuning against protected promotion evidence.

## 4. Successes and Next Steps

### What worked

Despite the limitations, the experiment proved several foundational capabilities:

- Language adherence reached `1.000`.
- Supported refusal reached `1.000`.
- Terminology validity reached `0.500`.
- JSON validity reached `0.500`.
- Training remained numerically stable in BF16.
- Validation loss consistently decreased within each run.
- Dynamic sequence trimming held peak allocated VRAM near 3.2 GiB.
- Held-out selection rejected a misleading promotion based on training or validation loss alone.

### Action plan for the next run

The strongest next controlled experiment should combine:

1. **Increased volume and diversity:** Add unique citation and incident examples using exact
   production-shaped identifiers, with additional Turkish coverage.
2. **Extended optimization:** Run for 100–300 optimizer steps using a constant or
   constant-with-warmup scheduler.
3. **Refined hyperparameters:** Compare rank 16/alpha 32 with the current rank 16/alpha 16 baseline,
   and test maximum gradient norms of `2.0` or `5.0` independently.
4. **Robust evaluation:** Build a larger and more diverse held-out development set to reduce metric
   variance while preserving the protected promotion corpora.

These variables should be staged rather than changed silently in a single run. Data coverage and
optimization duration should be tested first; rank/alpha and clipping effects should then be
isolated through controlled comparisons.

## Execution Integrity Note

The first attempted real run selected a non-deterministic memory-efficient attention backward
kernel. It was interrupted and excluded from candidate selection. Accepted candidates used pinned
eager attention, treated non-deterministic kernel selection as a hard error, and trimmed batches to
their actual rendered lengths.

## Related Evidence

- [WP5.3 acceptance evidence](../acceptance/phase-5-bounded-lora.md)
- [Bounded LoRA training contract](../training/phase-5-bounded-lora.md)
- [Phase 5 plan](../plans/phase-5.md)
- Candidate selection: `var/training/runs/bounded-candidate-selection-v1.json`
- Selected training report:
  `var/training/runs/phase5-r16-lr2e4-v1-deterministic/training-report.json`
- Selected held-out report:
  `var/training/runs/phase5-r16-lr2e4-v1-deterministic/held-out-behavior.json`
