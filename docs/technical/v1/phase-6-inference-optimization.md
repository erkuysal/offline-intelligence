# Technical Vision v1 — Phase 6 Quantization and Inference Optimization

Status: Next — barebones Q4 benchmark scope ready to begin

## Intent

Produce evidence-backed runtime profiles for constrained on-premise hardware. Optimization must
reduce storage or compute cost while preserving the grounded-answer, refusal, and authorization
quality established in earlier phases.

The first implementation intentionally measures and packages the already accepted Q4 base runtime.
Broad Q8/Q5/INT8/BF16 comparisons and kernel experiments are deferred until after Phase 8. The
bounded implementation checklist is the [Phase 6 plan](../../plans/phase-6.md).

## Comparison Space

- BF16 or FP16 reference artifacts
- INT8 and 4-bit transformer runtimes where supported
- GGUF Q8, Q5, and Q4 variants for llama.cpp
- CPU-only, GPU-offloaded, and hardware-specific profiles
- Base-model and accepted-adapter combinations

## Benchmark Contract

Every candidate should record:

- Model, adapter, quantization, runtime, and source revisions
- Artifact size and checksum
- Peak RAM and VRAM
- Startup and warm-up duration
- Mean and P95 time to first token and end-to-end latency
- Tokens per second under controlled concurrency
- Retrieval and generation quality report
- Hardware, operating system, driver, and build configuration

## Proposed Module and Function Map

| Proposed function/class | Used for | Why it should be separate |
| --- | --- | --- |
| `ArtifactManifest` | Model, adapter, tokenizer, quantization, source, and checksum metadata | Stops filenames from being treated as trustworthy identity |
| `convert_model()` | Produces one runtime format from pinned source weights | Makes conversion repeatable and auditable |
| `verify_converted_artifact()` | Checks structure, template compatibility, and smoke inference | Catches corrupt or mismatched output before long benchmarks |
| `collect_resource_samples()` | Samples RAM, VRAM, CPU, and wall time | Standardizes resource measurement across formats |
| `run_inference_benchmark()` | Executes warm-up and controlled prompt workloads | Separates startup, prompt processing, and generation |
| `run_quality_regression()` | Runs the Phase 4/5 evaluator | Makes quality a first-class optimization result |
| `compare_artifacts()` | Computes size, speed, memory, and quality deltas | Produces a reviewable promotion decision |
| `select_runtime_profile()` | Resolves an accepted artifact for known hardware | Avoids unsafe operator guesswork |

## Quantization Calculations

Ideal raw weight storage for `P` parameters at `b` bits is:

```text
ideal_weight_bytes = P × b / 8
ideal_compression_ratio = reference_bits / quantized_bits
```

Real files are larger because scales, zero points, tensor metadata, alignment, tokenizer data, and
some unquantized tensors add overhead. Reports therefore use measured disk size.

A simple affine quantizer illustrates the approximation:

```text
q = clamp(round(x / scale) + zero_point, q_min, q_max)
x_approx = scale × (q - zero_point)
```

GGUF may use different block-wise schemes, but the trade-off is the same: fewer bits reduce storage
and memory bandwidth while increasing approximation error.

## Performance Calculations

```text
cold_start_ms = ready_time - process_start_time
TTFT_ms = first_token_time - request_time
prompt_tokens_per_second = prompt_tokens / prompt_evaluation_seconds
generation_tokens_per_second = completion_tokens / generation_seconds
peak_memory = max(sampled_resident_or_device_memory)
```

Relative comparisons use a named reference artifact:

```text
speedup = candidate_tokens_per_second / reference_tokens_per_second
memory_reduction = 1 - candidate_peak_memory / reference_peak_memory
size_reduction = 1 - candidate_disk_size / reference_disk_size
quality_delta = candidate_quality - reference_quality
```

Warm and cold runs are separated. Benchmark controls keep prompts, retrieval context, sampling,
context length, completion limit, concurrency, and hardware state equal. Multiple observations and
mean/P50/P95 are reported; the fastest observation is not an acceptance result.

## Promotion Rules

- Compare identical prompts, datasets, seeds where applicable, and retrieval outputs.
- Reject variants that cross safety or quality regression tolerances even when faster.
- Maintain at least one portable CPU profile and explicit hardware compatibility metadata.
- Keep model-format conversion reproducible; do not rely on an operator's unrecorded local cache.
- Treat adapter merge and quantization order as a measured decision, not an assumption.

## Expected Deliverables

- Phase 6 plan and benchmark schema
- Reproducible conversion and benchmark commands
- Hardware-profile matrix and machine-readable reports
- Selected default and fallback artifacts with checksums
- Runtime configuration and operator sizing guidance
- Acceptance record documenting quality/performance trade-offs

## Dependency

Phase 6 consumes the base model and any accepted Phase 5 adapter. It must retain the Phase 2 model
gateway contract and run the Phase 4/5 evaluation gates against every promoted artifact.
