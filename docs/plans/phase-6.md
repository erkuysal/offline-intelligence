# Phase 6 Barebones Quantization and Inference Plan

Status: Ready to begin

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

- [ ] Define a versioned inference benchmark report
- [ ] Record model format, quantization, checksum, disk size, RAM/VRAM, startup, TTFT, end-to-end
  latency, throughput, and protected evaluation identity
- [ ] Make threshold misses and identity mismatches fail with non-zero status
- [ ] Add deterministic fake/static contract tests

## Work Package 6.1: Accepted Q4 Measurement

- [ ] Measure the accepted Q4 runtime on the existing protected English/Turkish corpus
- [ ] Record cold startup and steady-state performance separately
- [ ] Reuse the Phase 4 quality, safety, citation, refusal, and leak gates
- [ ] Store a checksum-addressed acceptance report

## Work Package 6.2: Minimal Optimization

- [ ] Record CPU and CUDA runtime configuration
- [ ] Verify the current context size, parallelism, GPU offload, and Flash Attention settings
- [ ] Make the accepted profile explicit and rollback-safe
- [ ] Avoid an unbounded format, kernel, or parameter sweep

## Barebones Definition of Done

- [ ] The existing Q4 artifact has a reproducible identity and benchmark report
- [ ] Quality and safety remain within the accepted base-model gates
- [ ] Startup and runtime resource measurements are machine-readable
- [ ] The selected inference profile starts, serves, stops, and restores cleanly
- [ ] Deferred Q8/Q5/INT8/BF16 comparisons are explicitly recorded as follow-on work
- [ ] Phase 7 can package the exact accepted model and runtime without hidden dependencies

## Deferred Until After Phase 8

- Broad Q8/Q5/Q4 comparison
- PyTorch/torchao quantization experiments
- Quantization-aware adapter comparison
- Kernel and speculative-decoding experiments
- Hardware-wide tuning beyond the current target machine
