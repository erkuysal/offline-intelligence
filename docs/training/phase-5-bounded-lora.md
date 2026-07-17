# Phase 5 Bounded LoRA Training

Work Package 5.3 trains one reproducible PEFT adapter candidate at a time. It does not promote or
deploy the result. The immutable run manifest and `training-report.json` are inputs to the separate
held-out evaluation and promotion workflow.

## Explicit run contract

`config/training/gemma3-1b-lora-v1.json` declares every supported training value: base revision,
package versions, seed, precision and fallback, sequence length, micro-batch and accumulation,
epoch and step bounds, gradient clipping, evaluation/checkpoint cadence, AdamW parameters, scheduler
and warmup, LoRA parameters, and the bounded search grid. The first search is limited to ranks `8`
and `16` and no more than two learning rates.

Each run combines that configuration with the validated dataset checksum and deterministic split
checksum. A SHA-256 fingerprint identifies the complete combination. A resume is rejected unless
the checkpoint manifest equals the requested manifest, including the fingerprint. The checkpoint
also records the shuffled example order and next position so a resume does not silently repeat or
skip examples.

## Loss mask and checkpoints

The trainer renders the pinned Gemma chat template and assigns labels only to assistant completion
content and its end-of-turn token. System text, user text, assistant role headers, and padding use
the `-100` ignore index. Prefix stability is checked while producing every mask; a template that
cannot prove the completion boundaries stops the run.

PEFT writes `adapter_model.safetensors` and `adapter_config.json`. Checkpoints are rejected if those
files are absent or if a base-model weight file is present. Optimizer, scheduler, sampler, random,
and metric state are stored separately for exact local resume; frozen base weights are never saved.

## Run one candidate

This command starts a real CUDA training job. Confirm the validated manifest is an authorized
training corpus and notify other GPU users before running it:

```bash
conda run -n offline-ai-training python manage.py training-run \
  --manifest training/datasets/<dataset>/manifest.json \
  --output-dir var/training/runs/<candidate-id> \
  --rank 8 \
  --learning-rate 0.0001 \
  --local-files-only
```

Omit `--local-files-only` only when an authenticated download of the pinned revision is intended.
Use `--resume-from <checkpoint-directory>` to resume. The output directory must be empty to prevent
overwriting evidence.

The training report records validation losses, unclipped gradient norms, peak allocated/reserved
VRAM, assistant tokens per second, wall-clock duration, adapter identity, dataset identity, base
revision, and the full run manifest. CUDA exhaustion, non-finite loss, invalid gradients, excessive
sequence length, dataset mismatch, and checkpoint mismatch stop with a non-zero status.

## Candidate selection boundary

Training loss is diagnostic only. Candidate selection requires held-out behavior metrics and ranks
first by the number of missed held-out thresholds, then by behavior score. No adapter is eligible
for selection merely because its training or validation loss is lower. Runtime export and the
four-mode production evaluation remain Work Packages 5.4 and 5.5.

## Controlled v2 data/schedule iteration

The follow-up experiment uses `config/training/gemma3-1b-lora-v2.json` and dataset version `2.0.1`.
It holds the v1 winning rank, alpha, learning rate, clipping, and target modules fixed while using
420 training examples and a 159-step constant-with-five-step-warmup schedule:

```bash
conda run -n offline-ai-training python manage.py training-run \
  --config config/training/gemma3-1b-lora-v2.json \
  --manifest training/datasets/phase5-behavior-training-v2/manifest.json \
  --output-dir var/training/runs/<candidate-id> \
  --rank 16 \
  --learning-rate 0.0002 \
  --local-files-only
```

Training-framework evaluation must stop on both tokenizer EOS and Gemma `<end_of_turn>`; otherwise
decoded post-turn generation can invalidate an otherwise correct first response.

## Production-contract v3 corrective run

The v2 production rejection showed that development success did not transfer to the real RAG
prompt and output contracts. The v3 corrective corpus therefore renders the actual folded-system
RAG message, `[Source N]` labels, production JSON schemas, and production incident headings. Its
600 examples are balanced across six tasks and two languages: 480 training and 120 validation.
The independently authored 240-case development corpus is a separate manifest whose examples are
all assigned `held_out`; it is never consumed by optimization.

The bounded v3 run has one candidate: rank 16, alpha 32, learning rate `2e-4`, gradient norm 2.0,
and a constant schedule after five warmup updates. With 480 training examples, accumulation 8, and
three epochs, the effective bound is 180 optimizer updates (below the hard 200-step ceiling).

```bash
conda run -n offline-ai-training python manage.py training-run \
  --config config/training/gemma3-1b-lora-v3.json \
  --manifest training/datasets/phase5-behavior-training-v3/manifest.json \
  --output-dir var/training/runs/<v3-candidate-id> \
  --rank 16 \
  --learning-rate 0.0002 \
  --local-files-only
```

Evaluate only against the separate development manifest, while independently binding the training
report to the training corpus checksum:

```bash
conda run -n offline-ai-training python manage.py training-evaluate-candidate \
  --config config/training/gemma3-1b-lora-v3.json \
  --training-manifest training/datasets/phase5-behavior-training-v3/manifest.json \
  --manifest training/datasets/phase5-behavior-development-v3/manifest.json \
  --adapter var/training/runs/<v3-candidate-id>/adapter \
  --training-report var/training/runs/<v3-candidate-id>/training-report.json \
  --output var/training/runs/<v3-candidate-id>/development-report.json \
  --local-files-only
```

Passing this development proxy permits export testing only. It cannot authorize production
promotion; the protected base/adapter and RAG/no-RAG runtime matrix remains mandatory.

The real v3 run completed at 180 updates. Development behavior (`0.8611`) and deployed GGUF parity
(`0.8234` PEFT/runtime F1) passed, but validation loss rose from `0.3455` at step 20 to `0.6340` at
step 180. The production matrix then failed 11 gates, so the adapter is rejected and remains opt-in
negative evidence. See `docs/acceptance/phase-5-promotion-v3.md` and
`docs/post-mortem/run_analysis_2026-07-17_wp5.5_v3.md`.

## Export and runtime activation

Export the selected adapter only after its training and held-out selection reports pass:

```bash
conda run -n offline-ai-training python manage.py training-export-adapter \
  --config config/training/gemma3-1b-lora-v2.json \
  --adapter var/training/runs/<run>/adapter \
  --training-report var/training/runs/<run>/training-report.json \
  --selection-report var/training/runs/bounded-candidate-selection-v2.0.1.json \
  --output-dir var/training/adapters/<adapter-id> \
  --base-model-dir ~/.cache/huggingface/hub/models--google--gemma-3-1b-it/snapshots/<revision>
```

Start the base or adapted runtime explicitly:

```bash
LLAMA_PROFILE=gemma3-1b-base scripts/models/start-llm.sh
LLAMA_PROFILE=gemma3-1b-v2-adapter scripts/models/start-llm.sh
```

The adapted profile is fail-closed: path, manifest, ID, SHA-256, scale, GGUF filename, and accepted
runtime base must agree before llama.cpp starts. Clearing the adapter fields or selecting the base
profile restores the adapter-free command without migration. `/lora-adapters`, `/health/llm`, and
`/health/runtime` provide runtime and application identity evidence.

For Compose production profiles, place the approved GGUF adapter under `MODEL_DIR` and set
`LLM_ADAPTER_FILE`, `LLM_ADAPTER_SCALE`, `LLM_ADAPTER_ID`, and `LLM_ADAPTER_SHA256`. Leaving
`LLM_ADAPTER_FILE` empty preserves the previous command. Both CPU and GPU model services verify the
adapter checksum before adding `--lora-scaled`; the API receives the same ID and checksum.

Use `training-evaluate-runtime-adapter` to rerun the exact training-framework case IDs through the
deployed OpenAI-compatible endpoint. The resulting report records per-case outputs, semantic parity,
exact-match rate, behavior metrics, and runtime drift thresholds.
