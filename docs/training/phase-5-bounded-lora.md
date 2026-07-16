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
