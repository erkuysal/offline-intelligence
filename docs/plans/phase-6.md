# Phase 6 Barebones Quantization and Inference Plan

Status: Closed — barebones Q4 runtime accepted

## Scope Decision

Phase 6 preserves the accepted base-only Q4 runtime and builds the smallest reproducible
quantization and benchmark boundary around it. A broad quantization search is deferred until after
the initial eight-phase structure is complete.

## Accepted Starting Point

- Runtime model: `ggml-org/gemma-3-1b-it-GGUF:Q4_K_M`
- Runtime revision: `61333bac858461ec0c309b7baafdc408d7d2c381`
- File SHA-256: `8ccc5cd1f1b3602548715ae25a66ed73fd5dc68a210412eea643eb20eb75a135`
- Runtime: pinned CUDA llama.cpp server
- Product mode: base model plus permission-aware dense RAG
- Adapter mode: optional infrastructure only; no adapter is promoted

## Work Package 6.0: Benchmark Contract

- [x] Define a versioned inference benchmark report
- [x] Record model format, quantization, checksum, disk size, RAM/VRAM, startup, TTFT, end-to-end
  latency, throughput, and protected evaluation identity
- [x] Make threshold misses and identity mismatches fail with non-zero status
- [x] Add deterministic fake/static contract tests

WP6.0 is implemented by the strict models in
`apps/api/app/evaluation/inference_benchmark.py`, the accepted-runtime contract in
`config/models/gemma3-1b-q4-benchmark-v1.json`, and the
`./manage.py inference-benchmark-report` command. The command returns `1` for a valid report that
misses a gate and `2` for malformed evidence. Runtime measurement collection remains WP6.1.

## Work Package 6.1: Accepted Q4 Measurement

- [x] Measure the accepted Q4 runtime on the existing protected English/Turkish corpus
- [x] Record cold startup and steady-state performance separately
- [x] Reuse the Phase 4 quality, safety, citation, refusal, and leak gates
- [x] Store a checksum-addressed acceptance report

The accepted report SHA-256 is
`42a5d2dff06a3fea28950d1d4226bc0dabdbee9d13d7271ae3146eaf1c4fe357`; see
`docs/acceptance/phase-6-q4-benchmark.md` for the bounded measurement and quality outcomes.

## Work Package 6.2: Minimal Optimization

- [x] Record CPU and CUDA runtime configuration
- [x] Verify the current context size, parallelism, GPU offload, and Flash Attention settings
- [x] Make the accepted profile explicit and rollback-safe
- [x] Avoid an unbounded format, kernel, or parameter sweep

The accepted `config/models/gemma3-1b-base.env` profile uses the pinned CUDA llama.cpp build, 4,096
tokens of context, one slot, 99 configured GPU layers with all 27 model layers observed offloaded,
and Flash Attention. Startup and shutdown restored both model ports cleanly.

## Barebones Definition of Done

- [x] The existing Q4 artifact has a reproducible identity and benchmark report
- [x] Quality and safety remain within the accepted base-model gates
- [x] Startup and runtime resource measurements are machine-readable
- [x] The selected inference profile starts, serves, stops, and restores cleanly
- [x] Deferred Q8/Q5/INT8/BF16 comparisons are explicitly recorded as follow-on work
- [x] Phase 7 can package the exact accepted model and runtime without hidden dependencies

## Deferred Until After Phase 8

- Broad Q8/Q5/Q4 comparison
- PyTorch/torchao quantization experiments
- Quantization-aware adapter comparison
- Kernel and speculative-decoding experiments
- Hardware-wide tuning beyond the current target machine
