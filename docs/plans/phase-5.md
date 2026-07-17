# Phase 5 Model Adaptation Plan

Status: Closed with base-only runtime (adaptation infrastructure accepted; v2/v3 adapters rejected)

## Entry Criteria

Phase 5 starts from the accepted Phase 4 retrieval and generation floor:

- [x] Dense retrieval is the evidence-backed default
- [x] The 40-case English/Turkish full RAG baseline is reproducible
- [x] Refusal accuracy is `1.0` and restricted-fact leaks are `0`
- [x] Citation, faithfulness, hallucination, and streaming metrics have explicit gates
- [x] The production inference boundary is an OpenAI-compatible `llama-server`
- [x] Local training hardware is identified: RTX 5070 with 12,227 MiB VRAM, Ryzen 9 9950X,
  and 30 GiB system RAM

Phase 5 adapts behavior, not organizational knowledge. Private or changeable source facts remain in
permission-aware RAG and must not be memorized into an adapter.

## Initial Decisions

These decisions bound the first experiment. A measured failure may replace one through an ADR; it
must not be worked around silently.

| Area | Initial decision |
| --- | --- |
| Base family | Start from the trainable Hugging Face Gemma 3 1B instruction checkpoint corresponding to the accepted `gemma-3-1b-it` GGUF runtime family |
| Continuity gate | Pin the source checkpoint revision and prove base-checkpoint versus accepted-GGUF behavior before adapter promotion |
| Training method | Supervised fine-tuning with LoRA; keep base weights frozen |
| Stack | Pinned PyTorch, Transformers, TRL, PEFT, Datasets, Accelerate, and Safetensors in a separate project training environment |
| Precision | BF16 where the calibration test proves support; FP16 is the recorded fallback |
| Initial sequence limit | Calibrate at 1,024/2,048; approve 1,024 tokens for training until 2,048 has physical-VRAM headroom |
| Loss | Assistant/completion tokens only; system, user, retrieved context, and padding tokens are masked |
| Initial adapter search | One bounded comparison around rank `8` and `16`; record alpha, dropout, target modules, learning rate, and seed |
| Deployment | Export adapter-only Safetensors, convert it to a GGUF LoRA adapter, and load it alongside the immutable base model in `llama-server` |
| Promotion comparison | Base + RAG versus adapter + RAG; base-only and adapter-only are diagnostics |
| Phase boundary | Adapter training and deployment belong here; quantization comparisons remain Phase 6 |

Google documents Gemma tuning with Transformers and PEFT and recommends matching the training
framework to the intended deployment format. TRL supports completion/assistant-only loss and PEFT
adapter training. `llama.cpp` provides PEFT-to-GGUF LoRA conversion and server-side adapter loading.
The exact tool and model revisions are recorded by Work Package 5.0, rather than following moving
default branches.

## Artifact Layout

The implementation should establish these boundaries without adding training dependencies to the
API runtime image:

```text
config/training/                 pinned experiment configurations
training/datasets/              manifests and reviewable examples
training/schemas/               versioned JSON schemas
training/runs/<run-id>/          metrics, logs, environment and checkpoint references
training/adapters/<adapter-id>/  promoted adapter, manifest and checksums
apps/api/app/evaluation/         shared product-quality evaluation
scripts/training/                validation, train, export and compatibility entry points
```

Large model weights, optimizer states, raw checkpoints, and sensitive datasets remain outside Git.
Git stores schemas, manifests, small approved examples, checksums, configuration, reports, and
acceptance evidence.

## Work Package 5.0: Reproducible Training Foundation

### Environment and hardware calibration

- [x] Add a separate, pinned training environment without changing production API dependencies
- [x] Record Python, CUDA, driver, GPU, PyTorch, Transformers, TRL, and PEFT versions; the
  deployment llama.cpp revision remains part of the base-equivalence gate
- [x] Resolve and pin the exact trainable Gemma source checkpoint and license terms
- [x] Verify its tokenizer and chat template against the production prompt contract
- [x] Run a one-batch BF16 forward/backward calibration at 1,024 and 2,048 tokens
- [x] Record peak VRAM, system RAM, step time, and whether gradient checkpointing is required;
  2,048 tokens executes but exceeds the physical-VRAM headroom gate and is not yet training-safe
- [x] Fail with an actionable error when CUDA, BF16, the checkpoint access token, packages, or free
  disk space is unavailable

### Base equivalence gate

- [x] Evaluate the unadapted source checkpoint on a deterministic diagnostic slice
- [x] Evaluate the corresponding unadapted GGUF artifact through `llama-server`
- [x] Compare formatting, refusal, citations, and expected facts under the same prompt
- [x] Record acceptable conversion/runtime drift before any adapter training result is considered
- [x] Write an ADR for the checkpoint, stack, precision, chat template, and deployment path

### Exit criteria

- [x] A clean checkout can recreate the environment from pinned inputs
- [x] A calibration report proves the selected micro-batch and 1,024-token training length fit in
  12,227 MiB; 2,048 remains an unapproved calibration probe
- [x] The source-to-GGUF comparison passes its recorded tolerance

## Work Package 5.1: Training Data Contract

### Schema and provenance

- [x] Define `TrainingExample` and `TrainingManifest` schemas with stable IDs and versions
- [x] Record task, language, messages, expected citations, source provenance, license, sensitivity,
  template family, grouping key, and intended split
- [x] Support grounded answers, grounded refusals, citation formatting, JSON output, incident reports,
  and terminology tasks in English and Turkish
- [x] Require explicit approval metadata for any non-public or synthetically generated example
- [x] Forbid secrets, credentials, personal data, restricted document text, and unverifiable targets

### Validation and splits

- [x] Validate roles, required fields, citation syntax, JSON schemas, language labels, and answer
  support through an independent verified-support record
- [x] Render with the pinned production chat template and reject sequences above the token limit
- [x] Detect exact duplicates and report near duplicates for review
- [x] Assign deterministic group-aware train, validation, and held-out splits
- [x] Keep paraphrases, translations, and examples from the same template family in one split
- [x] Reserve the Phase 4 corpus and questions as promotion evidence; never train on them
- [x] Emit task/language distributions, duplicate rates, rejection reasons, and dataset checksums

### Exit criteria

- [x] Invalid or sensitive examples make validation fail with a non-zero exit code
- [x] Re-running the same manifest and seed produces identical splits and checksums
- [x] Every accepted example has reviewable provenance, support review, and redistribution status

## Work Package 5.2: Evaluation Matrix

- [x] Reuse the Phase 4 evaluator for base, base + RAG, adapter, and adapter + RAG runs
- [x] Add task-level measures for language adherence, citation format, JSON schema validity, incident
  report structure, terminology consistency, and supported refusal
- [x] Report every quality and safety metric by language and task, not only as a global average
- [x] Store per-case outputs for regression diagnosis without persisting unauthorized source text
- [x] Separate dataset-validation, training, held-out behavior, and production-runtime reports
- [x] Make every promotion threshold produce a non-zero CLI exit when missed

## Work Package 5.3: Bounded LoRA Training

- [x] Implement configuration-driven adapter training with no hidden library defaults
- [x] Mask loss to assistant/completion tokens and test the produced label mask
- [x] Record base revision, dataset checksum, seed, rank, alpha, dropout, target modules, optimizer,
  scheduler, precision, batch sizes, accumulation, sequence length, and package revisions
- [x] Save adapter-only checkpoints, validation loss, gradient norms, peak memory, tokens per second,
  and wall-clock duration
- [x] Resume only when the checkpoint manifest exactly matches the run configuration
- [x] Stop on non-finite loss, invalid gradients, VRAM exhaustion, or dataset/checkpoint mismatch
- [x] Limit the first search to the recorded rank `8`/`16` configurations and at most two learning
  rates; expand only if held-out evidence justifies the cost
- [x] Select candidates using held-out behavior metrics, never training loss alone

Implementation, unit-contract verification, and the first real bounded `2 × 2` candidate grid are
complete. The initial winner failed development gates. A controlled v2 iteration expanded data and
optimization duration while holding the selected adapter hyperparameters fixed. The corrected
v2.0.1 adapter passed all 120 development held-out cases and is eligible for Work Package 5.4 export
testing. It is not promotion eligible; protected runtime and regression evidence remain required.

## Work Package 5.4: Adapter Export and Runtime Integration

- [x] Export adapter weights as Safetensors with tokenizer, chat-template, and base compatibility data
- [x] Generate SHA-256 checksums and an immutable adapter manifest
- [x] Convert the PEFT adapter to GGUF using a pinned llama.cpp converter revision
- [x] Reject unsupported target modules, added-token embeddings, or base architecture mismatches
- [x] Add an opt-in runtime adapter path and scale while preserving the adapter-free default
- [x] Expose active adapter ID and checksum through health/diagnostic metadata
- [x] Prove startup failure is actionable when an adapter is missing, corrupt, or incompatible
- [x] Prove disabling the adapter restores the exact prior base configuration without data migration
- [x] Compare the training-framework adapter and deployed GGUF adapter on the same deterministic cases

WP5.4 completed on 2026-07-17. The deployed adapter passed 120-case PEFT/GGUF compatibility with
`0.998380` parity F1 and `0.991667` task validity. One Turkish JSON output drifted to labeled prose,
so runtime integration is accepted but the candidate remains ineligible for promotion until WP5.5.

## Work Package 5.5: Promotion and Acceptance

An adapter is promoted only when adapter + RAG passes all protected Phase 4 gates and meets the
following initial targets on the untouched promotion corpus:

| Metric | Promotion target |
| --- | ---: |
| Parse success | `1.00` |
| Expected fact coverage | `>= 0.75` |
| Citation accuracy | `>= 0.75` |
| Citation coverage | `>= 0.80` |
| Answer faithfulness | `>= 0.75` |
| Hallucination rate | `<= 0.25` |
| Refusal accuracy | `1.00` |
| Restricted-fact leaks | `0` |
| Mean / P95 TTFT | no worse than the Phase 4 hard gates and no more than 20% regression versus the rerun base |
| Mean / P95 end-to-end latency | no worse than the Phase 4 hard gates and no more than 20% regression versus the rerun base |
| Throughput | `>= 20` tokens/s and no more than 20% regression versus the rerun base |

In addition:

- [ ] No English/Turkish task slice may hide a material regression behind the overall score
- [ ] JSON and incident-report tasks pass their schema/structure gates
- [x] Base + RAG and adapter + RAG are evaluated from the same corpus, prompts, retrieval results,
  generation settings, and runtime build
- [ ] The deployed GGUF adapter passes the same gates as the training-framework adapter
- [ ] Activation and rollback pass production-profile smoke and browser chat tests
- [x] The decision is recorded as accepted or rejected; a rejected adapter is not made the default

The v2 adapter was rejected on 2026-07-17. Adapter+RAG failed five strict behavior gates and the
protected regression quality gates; Turkish faithfulness was `0.2000`, protected fact coverage was
`0.3906`, and protected hallucination was `0.5938`. The base-only profile remains the default. The
failed matrix and all nine source artifacts are checksum-indexed with `promotion_passed: false`.

Corrective v3 readiness is complete: a 600-example production-prompt training/validation corpus and
a separately authored 240-case development corpus both pass the deterministic data contract. The
single bounded candidate uses rank 16/alpha 32, `2e-4`, a five-step constant warmup, gradient norm
2.0, and at most 180 effective optimizer updates. No v3 training or promotion claim has yet run.

The v3 run subsequently completed, passed independent development and PEFT/GGUF compatibility, but
was rejected by the production matrix on 2026-07-17. Eleven behavior, protected-quality, refusal,
and relative-TTFT gates failed. The base-only profile remains default; v3 is negative evidence.

## Barebones Closure Decision

Phase 5 is closed without a promoted adapter. The reproducible data, training, evaluation, export,
activation, rollback, and evidence machinery is retained as a working extension point. The accepted
product outcome is the existing base Q4 model with permission-aware RAG. Further dataset iteration,
checkpoint selection, and adapter promotion are deferred until after the initial eight-phase roadmap.

Unchecked promotion criteria below describe what a future adapter must satisfy; they no longer block
progression to Phase 6 because no adapter is being activated as the product default.

## Phase 5 Definition of Done

- [ ] Training data is versioned, provenance-aware, validated, deduplicated, and leakage-safe
- [ ] Training is reproducible from pinned configuration and produces traceable adapter artifacts
- [ ] Evaluation compares all four required model/RAG modes on held-out English/Turkish cases
- [ ] Safety, authorization, refusal, quality, and performance gates are automated
- [ ] The adapter can be activated and rolled back through the existing inference boundary
- [ ] Runtime images remain independent of the training toolchain
- [ ] ADRs, operator documentation, reports, and acceptance/rejection evidence agree
- [ ] English and Turkish roadmaps record the final Phase 5 outcome

## Explicit Non-Requirements

- Training private document facts into model weights
- Replacing retrieval permissions or grounded refusal with model behavior
- Full-model fine-tuning or an unbounded hyperparameter sweep
- Promoting an adapter from training loss or qualitative examples alone
- Quantization comparisons, speculative decoding, or native kernels
- Redistributing model or dataset artifacts without verified license permission

## Primary References

- [Google Gemma model fine-tuning](https://ai.google.dev/gemma/docs/tune)
- [Hugging Face PEFT documentation](https://huggingface.co/docs/peft/index)
- [Hugging Face TRL SFT Trainer](https://huggingface.co/docs/trl/sft_trainer)
- [llama.cpp PEFT LoRA to GGUF converter](https://github.com/ggml-org/llama.cpp/blob/master/convert_lora_to_gguf.py)
- [llama.cpp server LoRA adapter contract](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
