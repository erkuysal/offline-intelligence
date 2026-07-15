# Phase 5 Training Foundation

This guide covers the isolated Work Package 5.0 environment, preflight, and one-step LoRA memory
calibration. It does not train or promote an adapter.

## Pinned baseline

| Item | Pin |
| --- | --- |
| Source model | `google/gemma-3-1b-it` |
| Source revision | `dcc83ea841ab6100d6b47a070329e1ba4cf78752` |
| Source format | BF16 Safetensors, gated by the Gemma license |
| License record | Terms last modified `2026-04-01`; access confirmed `2026-07-15` |
| Accepted Phase 4 runtime | `ggml-org/gemma-3-1b-it-GGUF:Q4_K_M` revision `61333bac858461ec0c309b7baafdc408d7d2c381` |
| Training environment | `offline-ai-training`, Python 3.12.11 |
| PyTorch/CUDA runtime | PyTorch 2.13.0 with its CUDA 13.0 dependencies |
| Training libraries | Transformers 5.13.1, TRL 1.8.0, PEFT 0.19.1 |
| Local hardware gate | RTX 5070, at least 12,000 MiB VRAM, compute capability 12.0 |
| Chat template | `gemma3-production-folded-system-v1`, SHA-256 `d2f96210400e...` |

The full direct dependency set is recorded in `environment.training.yml`; the experiment and model
contract is recorded in `config/training/gemma3-1b-lora-v1.json`. Training dependencies are not
installed into the `offline-ai` API environment or production image.

## Create the environment

From the repository root:

```bash
PIP_NO_CACHE_DIR=1 conda env create -f environment.training.yml
```

To update an existing environment after an intentional pin change:

```bash
PIP_NO_CACHE_DIR=1 conda env update -n offline-ai-training -f environment.training.yml --prune
```

Do not update individual packages in place and continue using the same experiment ID. Change the
configuration, recreate the environment, and record the reason.

The clean-recreation gate was exercised on 2026-07-15 with a second environment created only from
this file. Exact-package preflight and local-only tokenizer/template checks both passed before that
environment was used for any separate diagnostics.

## Authorize the gated source model

1. Review and accept the Gemma usage license on the
   [official model page](https://huggingface.co/google/gemma-3-1b-it).
2. Create a read-only Hugging Face token.
3. Store it using the Hugging Face CLI, outside this repository:

```bash
conda run -n offline-ai-training hf auth login
conda run -n offline-ai-training hf auth whoami
```

Alternatively, supply `HF_TOKEN` only to the command process. Never put the token in a tracked env
file, training configuration, report, shell script, or command transcript. Preflight reports record
only whether usable credentials were found.

## Run preflight

The preflight is read-only apart from its JSON report under ignored `var/` storage:

```bash
conda run -n offline-ai-training python manage.py training-preflight
```

It verifies exact Python and direct package versions, GPU identity, VRAM, compute capability,
PyTorch CUDA access, BF16 support, free disk space, and the presence of gated-model credentials. A
failed check returns a non-zero status and an actionable explanation.

## Run the calibration gate

Calibration downloads the pinned model on the first authenticated run. It performs one LoRA
forward/backward optimizer step at 1,024 and 2,048 tokens with micro-batch size one. It records step
time, peak allocated/reserved VRAM, precision, device data, and parameter counts:

```bash
conda run -n offline-ai-training python manage.py training-calibrate
```

After the pinned snapshot is cached, enforce offline operation with:

```bash
HF_HUB_OFFLINE=1 conda run -n offline-ai-training \
  python manage.py training-calibrate --local-files-only
```

Reports are written to `var/training/` by default and must not contain model tokens or private
training examples. A successful memory calibration does not authorize training; chat-template
equivalence and dataset validation remain separate gates.

## Recorded calibration

The authenticated and cached source revision passed one BF16 LoRA optimizer step at both probe
lengths on the RTX 5070. A direct comparison also passed without gradient checkpointing, so the
pinned configuration leaves it disabled.

| Sequence length | Step time | Peak allocated | Peak reserved | Assessment |
| ---: | ---: | ---: | ---: | --- |
| 1,024 | 1.318 s | 7,549.6 MiB | 8,106.0 MiB | Training headroom available |
| 2,048 | 0.893 s | 13,194.8 MiB | 14,300.0 MiB | Probe passes, but no physical-VRAM headroom |

A separately timed cached run used 2,724 MiB peak process resident system memory with no swaps.
The 2,048-token result exceeds the GPU's 12,227 MiB physical capacity in PyTorch allocator
statistics. It proves that the single probe executes, but it does not yet prove a stable long-run
training configuration. The first training configuration must reduce the sequence limit or prove a
memory strategy with an explicit safety margin before Work Package 5.0 exits.

## Verify prompt and runtime continuity

The pinned tokenizer must contain the complete 262,144-token vocabulary and map
`<start_of_turn>`/`<end_of_turn>` to IDs 105/106. The verifier rejects the incomplete placeholder
tokenizer that Transformers can otherwise construct when tokenizer assets are absent:

```bash
conda run -n offline-ai-training python manage.py training-template-check --local-files-only
```

Gemma 3 instruction checkpoints support `user` and `model` turns rather than a separate system
turn. The pinned template therefore prepends the production system contract to the first user turn.
It matches the chat template embedded in the accepted GGUF and is used for both training rendering
and source-model diagnostics.

With the accepted GGUF running through `llama-server` on port 18080, run:

```bash
conda run -n offline-ai-training python manage.py training-continuity \
  --local-files-only --runtime-url http://127.0.0.1:18080/v1
```

The five-case English/Turkish diagnostic requires both models to preserve expected facts, grounded
refusal, and document-instruction isolation. Exact text equality is not required. Citation drift is
bounded separately: the GGUF citation rate must be at least 0.75 and no more than 0.25 below the
source checkpoint. The accepted result was source `1.00`, GGUF `0.75`, drift `0.25`.

The accepted repository commit is `61333bac858461ec0c309b7baafdc408d7d2c381`; the tested Q4_K_M
file SHA-256 is `8ccc5cd1f1b3602548715ae25a66ed73fd5dc68a210412eea643eb20eb75a135`.
The local cache may place this unchanged file under a later metadata-only repository snapshot.

## Failure boundaries

- Missing CUDA, BF16 support, disk, packages, or credentials stops preflight.
- An inaccessible or mismatched model revision stops calibration.
- CUDA out-of-memory stops the calibration and identifies the failing sequence length.
- The source revision is never replaced with `main` or an unpinned local directory.
- Model weights, caches, optimizer state, and raw checkpoints remain outside Git.
