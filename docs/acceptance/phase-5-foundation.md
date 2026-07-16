# Phase 5 Training Foundation Acceptance

Date: 2026-07-15
Status: Work Package 5.0 accepted; Work Package 5.1 accepted separately

## Accepted Evidence

- Exact source model, environment, package versions, license record, tokenizer, and chat template
  are pinned.
- RTX 5070 CUDA and BF16 preflight passes.
- One-step BF16 LoRA calibration executes at 1,024 and 2,048 tokens.
- The 1,024-token probe has physical-VRAM headroom; 2,048 tokens does not.
- The tokenizer/template gate rejects incomplete caches and matches llama.cpp's embedded template.
- Five deterministic source-versus-GGUF cases preserve facts, refusal behavior, and
  document-instruction isolation.
- Citation rate is 1.00 for BF16 source and 0.75 for Q4_K_M, within the recorded 0.25 drift limit.
- The GGUF file identity is pinned by repository commit and SHA-256.
- The canonical `build-cuda` uses llama.cpp `c198af4dc`, CUDA 13.0, GCC 13.4, and architecture
  `120a`. Its embedded runtime path resolves CUDA from `offline-ai-llama-build`, not the incompatible
  system CUDA 13.3 installation.
- Host verification detects the RTX 5070 without `LD_LIBRARY_PATH`. The accepted Gemma Q4_K_M
  artifact loads through the CUDA build and completes an OpenAI-compatible chat request at about
  280 generated tokens per second in the smoke probe.
- A second environment named `offline-ai-training-repro` was created only from
  `environment.training.yml`. Before any diagnostic build tools were added, its exact-package,
  CUDA/BF16, authentication, tokenizer, and chat-template checks all passed. The retained reports
  are `var/training/preflight-repro.json` and `var/training/template-check-repro.json`.

## Follow-on Gate

- [x] Repair the llama.cpp CUDA build before deployment performance evaluation.
- [x] Complete and accept the Work Package 5.1 training-data contract.

No adapter training or promotion is authorized by this acceptance record.
