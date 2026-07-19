# Phase 6 Benchmark Contract Acceptance

Date: 2026-07-19

Status: Accepted for WP6.0

## Outcome

The repository now has a versioned, machine-readable boundary for evaluating the accepted Gemma 3
1B Q4_K_M base runtime. This work does not claim new runtime measurements; it defines how WP6.1
must supply and gate them.

## Implemented Boundary

- `config/models/gemma3-1b-q4-benchmark-v1.json` pins the model ID, repository revision, GGUF
  format, Q4_K_M quantization, file size and SHA-256, llama.cpp revision, and initial gates.
- `apps/api/app/evaluation/inference_benchmark.py` strictly validates the contract, runtime
  measurement, protected quality report, and composed benchmark report.
- `./manage.py inference-benchmark-report` creates the final report and exits with:
  - `0` when identity, quality, and performance gates pass;
  - `1` when valid evidence contains an identity or threshold failure;
  - `2` when an input is missing, malformed, or methodologically invalid.
- Protected prompts and answers are not copied into the benchmark. The final report records only
  evaluation identity, policy, pass/fail state, failure count, source path, and source SHA-256.

## Command

```bash
conda run --no-capture-output -n offline-ai ./manage.py inference-benchmark-report \
  --measurement var/inference/gemma3-1b-q4-measurement.json \
  --quality-report var/evaluation/generation-protected-q4.json \
  --output var/inference/gemma3-1b-q4-benchmark.json
```

WP6.1 will produce the two input reports through real model and embedding server runs. Those
servers are not started by the report-builder command.

## Verification

- Six deterministic benchmark tests pass.
- The tests cover successful composition, checksum identity drift, performance and protected
  quality failures, invalid latency ordering, CLI gate status `1`, and malformed-input status
  `2`.
- Ruff and mypy pass for the new module and affected command surface.

No LLM server, embedding server, or CUDA training process was started for WP6.0.
