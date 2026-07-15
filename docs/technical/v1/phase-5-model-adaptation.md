# Technical Vision v1 — Phase 5 Model Adaptation with LoRA and PEFT

Status: Next

## Intent

Improve repeatable model behavior without moving changeable organizational knowledge out of RAG.
LoRA/PEFT should teach response language, grounded refusal, citation style, structured output, report
formats, and terminology—not memorize private source documents.

## Target Capabilities

- Versioned and provenance-aware training examples
- English/Turkish grounded-answer, refusal, citation, JSON, and incident-report tasks
- Schema, citation, support, sensitive-data, duplication, and sequence-length validation
- Leakage-safe train, validation, and held-out evaluation splits
- Reproducible PEFT training configurations and run manifests
- Versioned adapter export, checksums, compatibility metadata, activation, and rollback
- Production inference through the existing model-backend contract

## Training and Promotion Flow

```text
Curated examples
  ↓ validation and deduplication
Chat-template conversion
  ↓ leakage-safe split
Base evaluation
  ↓
LoRA training
  ↓
Held-out adapter evaluation
  ↓ quality + safety + performance gates
Versioned adapter
  ↓
Optional runtime activation and rollback
```

The decisive comparison is base model + RAG versus adapter + RAG. Base-only and adapter-only runs
remain diagnostic controls. An adapter is promoted only when it materially improves selected Phase 4
quality metrics, preserves perfect refusal and zero restricted-fact leaks, and remains within agreed
latency limits.

## Key Technical Decisions to Make

- Trainable base checkpoint and its compatibility with the current GGUF runtime model
- GPU/VRAM envelope, precision, sequence length, and reproducibility constraints
- PEFT framework, chat template, target modules, rank, alpha, dropout, and optimizer schedule
- Adapter-only versus merged export and the llama.cpp deployment path
- Dataset licensing, sensitive-data policy, artifact retention, and redistribution rules
- Minimum improvement and maximum regression thresholds

Training should use a trainable PyTorch checkpoint. The current quantized GGUF artifact is an
inference format; it is not the direct training input. Export must prove that the evaluated adapter
and the deployed artifact are equivalent enough to pass the same gates.

## Proposed Module and Function Map

These names describe intended responsibilities; they are not implemented yet.

| Proposed function/class | Used for | Why it should be separate |
| --- | --- | --- |
| `TrainingExample` / `TrainingManifest` | Versioned task, messages, provenance, language, and split metadata | Prevents scripts from relying on unvalidated free-form JSON |
| `load_training_dataset()` | Loads one manifest and its examples | Gives every command the same version and reference checks |
| `validate_training_example()` | Checks roles, citations, support, language, JSON targets, and sensitive-data rules | Fails bad supervision before expensive training |
| `deduplicate_examples()` | Detects exact and near-duplicate prompts/answers | Reduces memorization and train/evaluation leakage |
| `assign_dataset_split()` | Creates deterministic group-aware train/validation/test partitions | Keeps related source templates out of different splits |
| `render_chat_template()` | Converts normalized messages into the base model's exact template | Training and inference formatting must match |
| `build_peft_config()` | Validates rank, alpha, dropout, and target modules | Makes adapter structure explicit and reproducible |
| `train_adapter()` | Runs masked supervised fine-tuning and emits checkpoints | Keeps training orchestration independent of dataset preparation |
| `evaluate_adapter()` | Executes base/RAG/adapter comparison through the accepted evaluator | Prevents training loss from becoming the promotion criterion |
| `export_adapter()` | Writes adapter weights, template metadata, manifest, and checksums | Makes the artifact deployable and traceable |
| `verify_adapter_compatibility()` | Checks base revision, architecture, target modules, and format | Prevents loading an adapter onto incompatible weights |

## LoRA Calculation

For a frozen base weight matrix `W` with shape `d_out × d_in`, LoRA learns two small matrices:

```text
A shape = r × d_in
B shape = d_out × r
effective_weight = W + (alpha / r) × (B × A)
```

For one adapted linear layer:

```text
base_parameters = d_out × d_in
LoRA_parameters = r × (d_in + d_out)
parameter_fraction = LoRA_parameters / base_parameters
```

For a `4096 × 4096` projection and `r=16`, the base layer has 16,777,216 parameters while the
adapter has 131,072—about 0.78% for that layer. Actual totals depend on the targeted attention and
MLP modules. `alpha/r` controls update scale; dropout regularizes only the adapter path.

## Training Objective and Masking

Supervised fine-tuning minimizes next-token cross entropy over intended assistant output tokens:

```text
loss = -mean(log P(target_token_t | preceding_tokens))
```

System, context, user, and padding tokens should normally be masked from the loss. They provide
conditioning but are not desired completions. This focuses limited adapter capacity on answer
behavior and avoids training the model to reproduce source context.

## Dataset Calculations

Splits should be deterministic from a stable grouping key such as source/template family:

```text
bucket = hash(dataset_version + group_id + split_seed) mod 100
```

Bucket ranges map to train, validation, and held-out test percentages. Grouping is more important
than the exact percentage: paraphrases or bilingual examples derived from one seed must stay in one
split.

Useful diagnostics include:

```text
duplicate_rate = duplicate_examples / all_examples
task_share(task) = examples_for_task / all_examples
language_share(lang) = examples_for_language / all_examples
citation_validity = valid_citation_examples / citation_examples
support_rate = supported_answer_claims / checked_answer_claims
```

Distributions are reported per task and language so an overall gain cannot hide a Turkish, refusal,
or structured-output regression.

## Memory and Compute Estimates

```text
weight_memory ≈ parameter_count × bytes_per_weight
adapter_memory ≈ trainable_parameters × bytes_per_weight
optimizer_memory ≈ trainable_parameters × optimizer_bytes_per_parameter
total_peak ≈ frozen_weights + adapter + gradients + optimizer + activations + runtime_overhead
```

BF16/FP16 weights use roughly two bytes per stored weight. Optimizer state needs multiple values per
trainable parameter, while activations vary with batch size, sequence length, checkpointing, and
attention implementation. This is a planning lower bound; a calibration batch must measure peak
memory.

```text
effective_batch = micro_batch × gradient_accumulation_steps × data_parallel_workers
tokens_per_step ≈ effective_batch × non_padding_sequence_tokens
```

## Evaluation and Promotion Calculations

For a metric where higher is better:

```text
absolute_gain = adapter_rag_metric - base_rag_metric
relative_gain = absolute_gain / max(abs(base_rag_metric), epsilon)
```

For hallucination and latency, lower is better, so improvement reverses the subtraction. Promotion
requires predefined gains on target metrics and maximum regressions on protected metrics. Refusal
accuracy must remain 1.0 and restricted-fact leaks must remain zero. Training loss only shows fit to
the training distribution; held-out RAG evaluation determines product improvement.

## Expected Deliverables

- `docs/plans/phase-5.md` with work packages and definition of done
- Versioned training-data schema, validator, and dataset manifest
- Reproducible training and evaluation commands
- Base, base + RAG, adapter, and adapter + RAG reports
- Adapter manifest and runtime configuration contract
- ADRs for the training stack, base checkpoint, and deployment format
- Acceptance or rejection record based on held-out evidence

## Non-Goals

- Memorizing customer documents in model weights
- Replacing retrieval authorization with model instructions
- Promoting an adapter because training loss decreased
- Broad pretraining or an unbounded hyperparameter search
- Quantization comparison, which belongs to Phase 6
