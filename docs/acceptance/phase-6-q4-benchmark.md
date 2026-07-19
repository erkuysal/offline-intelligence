# Phase 6 Accepted Q4 Benchmark

Date: 2026-07-19

Status: Accepted for the barebones Phase 6 scope

## Decision

Retain the existing adapter-free Gemma 3 1B IT Q4_K_M GGUF as the packaged generation runtime.
The exact artifact and pinned CUDA llama.cpp build passed identity, resource, performance, quality,
refusal, and authorization-leak gates. No broader quantization or kernel sweep was performed.

## Immutable Identity

| Field | Accepted value |
| --- | --- |
| Model | `ggml-org/gemma-3-1b-it-GGUF:Q4_K_M` |
| Model revision | `61333bac858461ec0c309b7baafdc408d7d2c381` |
| GGUF SHA-256 | `8ccc5cd1f1b3602548715ae25a66ed73fd5dc68a210412eea643eb20eb75a135` |
| Measured file size | 806,058,240 bytes |
| llama.cpp revision | `c198af4dc24f8e0ab8a569a60f931e03a192fd79` (build 9912) |
| Runtime profile | `config/models/gemma3-1b-base.env` |
| Adapter | Disabled |

## Hardware and Runtime

- Host: AMD Ryzen 9 9950X, 30,857 MiB system RAM, WSL2 Linux
- GPU: NVIDIA GeForce RTX 5070, 12,226 MiB reported VRAM
- Build: CUDA 13.0, architecture `1200`, GCC 13.4.0
- Runtime: 4,096-token context, one parallel slot, 99 configured GPU layers, Flash Attention enabled
- Observed offload: 27/27 model layers, including the output layer, placed on CUDA0
- llama.cpp projected device allocation: 852 MiB; this is runtime-reported because WSL did not
  expose reliable per-process VRAM attribution through `nvidia-smi`
- Process RAM high-water mark: 1,105.27 MiB

## Performance

| Metric | Result | Gate |
| --- | ---: | ---: |
| Cold startup | 1,528.23 ms | Recorded; no initial maximum |
| Internal warm-up | 49.51 ms | Recorded |
| Mean / P95 TTFT | 38.59 / 47.11 ms | <= 600 / 750 ms |
| Mean / P95 end-to-end | 112.79 / 185.42 ms | <= 1,200 / 1,600 ms |
| Mean generation throughput | 181.48 tokens/s | >= 20 tokens/s |

The steady-state figures cover 40 controlled cases at concurrency one. The cold-start figure comes
from llama.cpp's monotonic process log from initialization through the listening state.

## Quality and Safety

The existing bilingual `dense-baseline` 1.0.0 corpus and Phase 4 gates were reused in `base_rag`
mode.

| Metric | Result | Gate |
| --- | ---: | ---: |
| Parse success | 1.000 | >= 1.000 |
| Expected fact coverage | 0.703 | >= 0.650 |
| Citation accuracy | 0.656 | >= 0.650 |
| Citation coverage | 0.719 | >= 0.700 |
| Answer faithfulness | 0.656 | >= 0.650 |
| Hallucination rate | 0.344 | <= 0.350 |
| Refusal accuracy | 1.000 | >= 1.000 |
| Restricted fact leaks | 0 | <= 0 |

The result passes, but citation accuracy, faithfulness, and hallucination rate are close to their
gates. They remain explicit regression risks for later model or quantization changes.

## Evidence

- Benchmark report:
  `var/inference/by-sha256/42a5d2dff06a3fea28950d1d4226bc0dabdbee9d13d7271ae3146eaf1c4fe357.json`
- Benchmark report SHA-256:
  `42a5d2dff06a3fea28950d1d4226bc0dabdbee9d13d7271ae3146eaf1c4fe357`
- Runtime measurement SHA-256:
  `77832ca0e1675dea1d093941e63e5a025058038b42f48fc92c82168a75b63ccd`
- Quality report SHA-256:
  `2bdc4de060dc34cc9f465388cdf0e92507d5aa8b9a859916dfc1fe496abfb889`

Both the LLM and embedding services were stopped after measurement, and ports 8080 and 8081 were
verified closed.

## Deferred

Q8/Q5/BF16 comparisons, PyTorch/torchao quantization, speculative decoding, kernel sweeps, and
hardware-wide tuning remain deferred until after the initial eight-phase structure is complete.
