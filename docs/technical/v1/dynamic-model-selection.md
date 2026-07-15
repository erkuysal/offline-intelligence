# Dynamic Local Model Selection on the RTX 5070

Date: 2026-07-15

Status: Technical note and benchmark proposal; routing is not yet implemented

## Decision Summary

Offline Intelligence Hub can select models dynamically, but the first implementation should use a
small, controlled portfolio rather than an unrestricted model picker:

| Tier | Initial candidate | Installed locally | Purpose | Initial context | Promotion state |
| --- | --- | --- | --- | ---: | --- |
| `fast` | Gemma 3 1B IT Q4_K_M | Yes | Classification, rewriting, extraction, short low-risk answers | 4,096 | Accepted on CPU and GPU |
| `balanced` | Gemma 3 4B IT Q4_K_M | No | Default chat and grounded RAG | 8,192 | Download and benchmark first |
| `deep` | Gemma 3 12B IT Q4_K_M | No | Difficult reasoning and code tasks | 4,096 initially | Benchmark-gated; memory is tight |

The application should choose a stable alias (`fast`, `balanced`, or `deep`) from deterministic
request features. The llama.cpp router should own model loading, unloading, and least-recently-used
eviction. Start with one resident generation model (`--models-max 1`) because this GPU has 12 GiB,
not enough VRAM to keep the proposed balanced and deep models resident together.

This is a sizing recommendation, not an acceptance result. Only the existing 1B model has a
measured token-rate anchor suitable for the projection table. The installed Llama 8B has real
workflow timing samples, but not a controlled resource benchmark. All other resource and speed
figures below are engineering projections that must be replaced by controlled measurements before
promotion.

## Hardware and Workload Baseline

The target machine has:

- NVIDIA GeForce RTX 5070 with 12,227 MiB physical VRAM and 11,017 MiB observed free before loading
  the generation model (10.76 GiB usable at that moment)
- 6,144 CUDA cores and 672 GB/s advertised memory bandwidth
- AMD Ryzen 9 9950X and 30 GiB system RAM
- WSL, the pinned CUDA llama.cpp build `b9912-c198af4dc`, and full model offload
- one generation slot and one concurrent generation request
- a CPU-hosted embedding runtime and a disabled-by-default reranker, so their memory is not included
  in generation-model VRAM estimates

NVIDIA lists the desktop RTX 5070 with 12 GB GDDR7, a 192-bit interface, and 672 GB/s bandwidth.
The local `--list-devices` result is the source of the more precise MiB figures above. See the
[official RTX 5070 specifications](https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5070-family/).

The request schema accepts up to 4,096 generated tokens, while the current deployment setting caps
completions at 2,048. RAG can inject up to 12,000 characters of retrieved context, and generation
is serialized with `llm_max_concurrent_requests=1`. An 8K default context is therefore useful for
the balanced tier. The deep tier starts at 4K to protect VRAM and expands only after measurement.

Gemma 3 advertises a 32K context for 1B and 128K for 4B/12B, but those are architecture limits, not
safe local-runtime settings. KV cache grows with active context, and this product does not currently
need a 128K resident context. Runtime profiles should expose only measured 4K/8K limits initially.

## Units and Confidence

- Model repositories normally report decimal GB: 1 GB = 1,000,000,000 bytes.
- Linux and NVIDIA tools commonly report binary GiB or MiB: 1 GiB = 1,073,741,824 bytes.
- Disk size is not total VRAM. VRAM also contains KV cache, compute graph, CUDA/runtime buffers,
  and allocation slack.
- `Measured` means observed on this exact host. `Published` means an artifact/model publisher's
  value. `Projected` means a planning range derived from those two sources.

## Current Local Model Inventory

Inventory date: 2026-07-15

`Installed` means that a complete artifact is present in the local Hugging Face cache. It does not
mean that a model server is running. No chat, embedding, or reranker model server was running when
this inventory was taken.

| Artifact | Role | Local format and payload | Local snapshot | Installed | Acceptance/use state |
| --- | --- | ---: | --- | --- | --- |
| Gemma 3 1B IT | Chat and query rewriting | Q4_K_M GGUF, 806,058,240 bytes | `f9c28bcd8573` | Yes | Accepted Phase 2/5 runtime; current development default; CPU and RTX 5070 tested |
| Llama 3.1 8B Instruct | Larger chat comparison | Q4_0 GGUF, 6,036,116,480 bytes | `0aba27dd2f1c` | Yes | Accepted in the v0.4.0 real browser/RAG workflow; not the current default |
| Google Gemma 3 1B IT | Phase 5 training source | BF16 Safetensors, 1,999,811,208 bytes | `dcc83ea841ab` | Yes | Pinned training/calibration source; no trained adapter has been promoted |
| EmbeddingGemma 300M | Document embeddings | Q4_0 GGUF, 277,852,192 bytes | `8dd0ca2a66a8` | Yes | Accepted 768-dimensional embedding runtime |
| BGE Reranker v2 M3 | Retrieval reranking | Q4_K_M GGUF, 438,376,864 bytes | `3093af03b1a6` | Yes | Downloaded and evaluated; disabled by default because it added latency without accepted quality gain |

The Hugging Face cache reports approximately 9.0 GiB in total. The Gemma 3 1B GGUF currently has a
later metadata snapshot than the accepted repository commit, but the cached model blob retains the
accepted SHA-256 `8ccc5cd1f1b3602548715ae25a66ed73fd5dc68a210412eea643eb20eb75a135`.
The BF16 Gemma source and Q4 GGUF are two formats of the same base-model family, not two distinct
behavioral models.

The GGUF files under the llama.cpp source tree are vocabulary and tokenizer test fixtures. They are
not included in this inventory and should not be exposed as selectable runtime models.

## Installed and Proposed Portfolio

This is the complete planning view: production tiers, installed alternatives, auxiliary models,
and proposed comparison artifacts.

| Model | Intended place | Installed | Accepted for that place | Next action |
| --- | --- | --- | --- | --- |
| Gemma 3 1B IT Q4_K_M | `fast` generation tier and query rewrite | Yes | Yes | Re-benchmark with the standardized resource sampler |
| Gemma 3 4B IT Q4_K_M | `balanced` default generation tier | No | No | Next acquisition; benchmark at 4K and 8K |
| Gemma 3 12B IT Q4_K_M | `deep` generation tier | No | No | Acquire only after 4B results; probe at 4K with a 1 GiB VRAM-margin gate |
| Llama 3.1 8B IT Q4_0 | Installed generation comparison | Yes | Yes, for the v0.4.0 workflow | Retain as a benchmark candidate; do not make the bilingual default without evaluation |
| Qwen 2.5 14B IT Q4_K_M | Multilingual/code laboratory comparison | No | No | Defer; projected runtime memory is too close to the RTX 5070 limit |
| Whisper Large v3 Turbo | Proposed interactive speech-to-text service | No | No | Prefer as the first voice candidate; evaluate Turkish/English accuracy and latency |
| Whisper Large v3 | Proposed speech-to-text quality comparison | No | No | Compare against Turbo only after the voice pipeline exists |
| Google Gemma 3 1B IT BF16 | Phase 5 LoRA training base | Yes | Yes, as the pinned source | Continue Phase 5 work packages; keep separate from runtime artifacts |
| EmbeddingGemma 300M Q4_0 | Embedding service | Yes | Yes | Keep on CPU initially |
| BGE Reranker v2 M3 Q4_K_M | Optional reranking service | Yes | No default promotion | Keep disabled unless a later evaluation demonstrates quality gain |

No Gemma 3 4B, Gemma 3 12B, Qwen 2.5 14B, or Whisper artifact is currently installed. Model
acquisition must remain an explicit, pinned work-package action rather than an automatic side
effect of routing.

## Candidate Artifact Sizes

Only one quantization per promoted tier should be retained. Downloading every available quant
wastes storage and complicates artifact identity.

| Candidate artifact | Published or measured file size | Approx. GiB | Fit assessment |
| --- | ---: | ---: | --- |
| Gemma 3 1B IT Q4_K_M | 769 MiB local cache, measured | 0.75 | Very comfortable |
| Gemma 3 4B IT Q4_K_M | 2.49 GB, published | 2.32 | Comfortable; recommended default candidate |
| Gemma 3 4B IT Q8_0 | 4.13 GB, published | 3.85 | Comfortable, but slower and needs a measured quality case |
| Llama 3.1 8B IT Q4_0 | 6.04 GB, installed and measured | 5.62 | Fits; accepted comparison artifact |
| Gemma 3 12B IT Q4_K_M | 7.30 GB, published | 6.80 | Likely at 4K; benchmark required |
| Gemma 3 12B IT Q8_0 | 12.50 GB, published | 11.64 | Does not fit safely |
| Qwen 2.5 14B IT Q4_K_M | 8.99 GB, published | 8.37 | Artifact fits; runtime likely too close to the edge |

The Gemma sizes come from the official ggml-org
[4B GGUF repository](https://huggingface.co/ggml-org/gemma-3-4b-it-GGUF) and
[12B GGUF repository](https://huggingface.co/ggml-org/gemma-3-12b-it-GGUF). The Qwen size comes from
the official [Qwen 2.5 14B GGUF repository](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF).
The installed Llama row identifies the exact existing Q4_0 artifact. A different quantization must
be treated as a new candidate with its own revision, checksum, performance, and quality result.

Keeping the three proposed Gemma Q4 artifacts needs about 10.6 GB of payload storage. Allow
15–20 GB for these artifacts, repository metadata, download staging, and cache overhead. Keeping
the Llama and Qwen comparison artifacts as well raises the practical reserve to 30–40 GB. Hugging
Face snapshot directories can reference shared blobs, so directory totals must be interpreted with
care; the artifact manifest should record actual blob size and SHA-256.

## Projected Runtime Resource Envelope

These projections assume full CUDA offload, flash attention, one slot, no simultaneous training,
and an otherwise lightly loaded GPU. Ranges intentionally include allocator and desktop variance.

| Model/profile | VRAM at 4K context | VRAM at 8K context | Decode speed | Whole-host CPU | Decode GPU utilization |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gemma 3 1B Q4 | 1.3–2.0 GiB | 1.5–2.4 GiB | 220–320 tok/s | 2–8% | 25–65% |
| Gemma 3 4B Q4 | 3.2–4.3 GiB | 3.6–5.0 GiB | 140–220 tok/s | 3–10% | 50–85% |
| Gemma 3 4B Q8 | 4.8–6.0 GiB | 5.2–6.8 GiB | 90–150 tok/s | 3–11% | 55–90% |
| Llama 3.1 8B Q4_0 | 6.7–8.0 GiB | 7.3–9.1 GiB | 55–100 tok/s | 4–12% | 65–100% |
| Gemma 3 12B Q4 | 8.0–9.6 GiB | 8.8–10.8 GiB | 45–80 tok/s | 5–15% | 65–100% |
| Qwen 2.5 14B Q4 | 9.7–11.2 GiB | 10.5–12.7 GiB | 35–65 tok/s if fully offloaded | 5–18% | 75–100% |

The CPU percentages are fractions of the complete 32-thread host, not percentages of one core.
Tokenization and prompt ingestion can create short CPU bursts above the listed steady decode range.
GPU utilization is also workload-dependent: small models may be too small to saturate the GPU,
while prompt processing on larger batches can approach 100%.

The 1B smoke run is the sole measured performance anchor: approximately 287 prompt tokens/s and
280 generated tokens/s for a very short request. Total GPU use visible during that run was about
2,796 MiB, but that figure included pre-existing WSL/desktop use and an automatically configured
runtime, so it is not an isolated model-VRAM measurement. It should not be used as a precise
per-model value.

### Why the 14B Artifact Is Not a Safe Fit

At the observed free-memory point, the GPU has 10.76 GiB available. Retaining a 1.0–1.5 GiB safety
margin leaves a working budget of roughly 9.3–9.8 GiB. The Qwen Q4 weights alone occupy about
8.37 GiB.

For Qwen 2.5 14B, its published 48 layers, 8 key/value heads, and 128 head dimension imply an
unquantized KV allocation of approximately:

```text
KV bytes/token = 2 × layers × KV heads × head dimension × 2 bytes
               = 2 × 48 × 8 × 128 × 2
               = 196,608 bytes/token

KV at 4,096 tokens ≈ 0.75 GiB
KV at 8,192 tokens ≈ 1.50 GiB
```

Weights plus KV already reach about 9.12 GiB at 4K before graph and CUDA buffers. It may start under
ideal conditions or with quantized KV cache, but normal variance can trigger partial CPU offload or
out-of-memory failure. That makes it a laboratory comparison, not a production tier on this card.

### CPU Offload Changes the Performance Class

If a model spills into system RAM, llama.cpp can still run it, but the result no longer has the
latency profile in the table. CPU activity can expand across many cores, system RAM consumption
rises by the offloaded weight fraction plus working buffers, GPU utilization becomes uneven, and
decode speed may fall into the 10–30 tok/s range or below. The router should therefore reject a
profile that cannot maintain its required VRAM margin instead of silently declaring a partial
offload successful.

System RAM is adequate for one memory-mapped artifact and the application stack. During model
switches, page cache may temporarily retain much of both the old and new files. With 30 GiB RAM,
`--models-max 1`, serialized loading, and idle-model eviction are preferable to caching several
large models.

## How the Performance Projection Was Derived

Autoregressive decode often reads most model weights for each generated token. A simple upper
bound is therefore:

```text
bandwidth ceiling (tokens/s) = GPU memory bandwidth / resident weight bytes
```

For example, the 2.49 GB Gemma 4B artifact has a simplistic ceiling near 270 tokens/s on a
672 GB/s GPU. Real generation is lower because quantization metadata, KV operations, synchronization,
sampling, kernels, and compute are not free. The speed ranges use that ceiling and the measured 1B
result as sanity checks; they are not vendor benchmarks.

Q8 is not automatically better for this product. It approximately doubles weight traffic relative
to Q4 while quality gains may be small for a particular task set. Q8 should be promoted only when
the Phase 4/5 evaluation suite demonstrates a meaningful quality improvement.

Cold model-switch latency is expected to be roughly 1–3 seconds for 4B, 2–5 seconds for an 8B-class
model, and 3–8 seconds for 12B/14B when files are on local NVMe and reasonably warm in page cache.
Cold filesystem cache, antivirus scanning, WSL storage placement, and allocation cleanup can make
this substantially slower. Conversation pinning prevents users from paying that cost every turn.

## Expected Capability Differences

Google's official Gemma 3 instruction-tuned benchmarks show that the 4B model is a large step up
from 1B, while 12B adds a further reasoning and coding gain:

| Official benchmark | Gemma 3 1B IT | Gemma 3 4B IT | Gemma 3 12B IT |
| --- | ---: | ---: | ---: |
| FACTS Grounding | 36.4 | 70.1 | 75.8 |
| BIG-Bench Hard | 39.1 | 72.2 | 85.7 |
| Global-MMLU Lite | 34.2 | 54.5 | 69.5 |
| HumanEval | 41.5 | 71.3 | 85.4 |
| LiveCodeBench | 1.9 | 12.6 | 24.6 |

These scores come from the [Gemma 3 model card](https://ai.google.dev/gemma/docs/core/model_card_3)
and are not measurements of this product. They support using 4B as the normal tier rather than
calling 1B a general-purpose default. Product promotion still depends on our grounded-answer,
Turkish/English, citation, refusal, and prompt-injection evaluations.

The first portfolio stays within Gemma 3 to reduce variation in prompt templates, behavior, and
license handling. This does not make adapters portable: the Phase 5 Gemma 3 1B LoRA adapter is tied
to that base architecture and cannot be attached to the 4B or 12B model. Each promoted size needs
its own unadapted quality baseline and, if justified, separately trained adapter.

Llama 3.1 8B remains a useful comparison, but Meta's official card lists eight supported languages
and does not include Turkish. See the
[Llama 3.1 8B Instruct model card](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct).
Qwen 2.5 14B is a useful multilingual/code comparison, but its local memory envelope is the larger
problem. Neither should replace a Gemma tier until the same bilingual product suite demonstrates a
quality advantage large enough to justify the operational variation.

## Routing Architecture

```text
request + conversation state + retrieval metadata
                       |
                       v
              deterministic policy
                       |
              fast / balanced / deep
                       |
                       v
          whitelisted runtime model alias
                       |
                       v
       llama.cpp router: load, serve, sleep, evict
                       |
                       v
       response + selected-model observability
```

The current chat schema already has an optional `model` field, and the OpenAI-compatible backend
forwards it. That is sufficient as a transport field, but clients should not be allowed to submit
arbitrary model paths or repository identifiers. Add a product-facing `model_mode` (`auto`, `fast`,
`balanced`, `deep`) and resolve it server-side to a versioned allowlist.

The pinned llama.cpp server supports router mode when launched without one fixed model and given a
models directory or preset file. It supports automatic loading, explicit load/unload endpoints,
sleeping idle models, and LRU eviction. See the pinned
[llama.cpp router documentation](https://github.com/ggml-org/llama.cpp/blob/c198af4dc24f8e0ab8a569a60f931e03a192fd79/tools/server/README.md#router-mode).

### Initial Policy

Use deterministic, auditable rules before introducing a classifier model:

1. Respect an authorized explicit `fast`, `balanced`, or `deep` choice.
2. Pin the selected tier to the conversation so successive turns do not cause reload oscillation.
3. Route lightweight structured operations—query rewrite, intent classification, tagging, and
   bounded extraction—to `fast`.
4. Route ordinary chat and RAG to `balanced`.
5. Escalate to `deep` for complex code/reasoning requests, repeated failed grounded answers, or an
   explicit quality request, provided the deep model is healthy and has passed its resource gate.
6. Permit one-way escalation within a conversation; downgrade only on a new conversation or an
   explicit user action.
7. Fall back from an unavailable deep tier to balanced and return the actual selected alias in
   telemetry, never silently pretending the requested tier ran.

Prompt length alone is not task difficulty. Routing should combine input tokens, retrieved-context
tokens, requested output length, operation type, conversation history, and whether the task needs
code/reasoning. User content must not be able to inject a raw filesystem path or modify the routing
allowlist.

### Lifecycle Defaults

- `--models-max 1`
- one inference slot per loaded model
- full GPU offload required for accepted GPU profiles
- 4K context for fast and initial deep probes; 8K for balanced
- embeddings and reranking stay on CPU until separately benchmarked
- unload idle models after an observed, documented threshold
- preload balanced only if cold-start measurements show that it improves normal interaction
- no background model switch while another generation is active

## Telemetry and Acceptance Gates

Every request should record:

- requested mode, policy-selected alias, actual model revision, quant, and adapter revision
- routing reason code and whether a fallback occurred
- input, retrieved-context, cached, and output token counts
- queue time, model-load time, time to first token, prompt tokens/s, decode tokens/s, and total time
- peak process RAM, peak VRAM, CPU utilization, GPU utilization, and any offloaded layer count
- evaluation task class, language, citation outcome, refusal outcome, and user override

A candidate is promoted only if repeated cold and warm runs establish:

- no OOM and no unintended CPU offload
- at least 1.0 GiB steady-state VRAM margin under the intended context and desktop workload
- acceptable P50/P95 latency at concurrency one
- no regression beyond the established grounded-answer, citation, authorization, refusal, and
  bilingual quality tolerances
- pinned artifact source, revision, checksum, template, license record, and reproducible launch
  profile

Run routing in shadow mode first: compute and log the proposed tier while continuing to serve the
current fixed model. That produces a task distribution and estimated switch frequency without
changing user-visible behavior.

## Recommended Experiment Order

1. Establish a repeatable resource sampler and re-run the existing 1B profile at 4K with one slot.
2. Acquire only Gemma 3 4B Q4_K_M, pin its revision and SHA-256, and benchmark 4K then 8K.
3. Compare 1B and 4B on the current generation/RAG suite and Turkish/English task slices.
4. Implement alias resolution and shadow routing without enabling dynamic loading.
5. Acquire Gemma 3 12B Q4_K_M and probe 4K with a hard 1 GiB memory-margin gate.
6. Enable router mode with `--models-max 1`, conversation pinning, serialized switches, and
   balanced fallback.
7. Measure real switch frequency, cold-start cost, and quality lift before adding Llama or Qwen
   comparison artifacts.

The immediate next model should therefore be Gemma 3 4B IT Q4_K_M. It has enough capacity to be a
credible default, leaves generous VRAM headroom, keeps the current model family, and gives the
router a meaningful quality/speed distinction without making reliability depend on a borderline
fit.

## Proposed Sequential Voice Pipeline

Voice input does not require the speech and language models to perform inference at the same time.
For a single-user assistant, the natural lifecycle is temporal: listen first, reason second, then
return text or optionally synthesize speech.

```text
microphone audio
      |
      v
voice activity detection and bounded audio buffer
      |
      v
Whisper speech-to-text (ears)
      |
      v
validated transcript + language/timestamp metadata
      |
      v
text-model router and selected LLM (brain)
      |
      +----------------------> text response
      |
      v
optional text-to-speech service
      |
      v
speaker audio
```

Whisper performs speech recognition and speech translation; it does not synthesize voice. A text
response needs only Whisper plus the LLM. Spoken responses add an independently selected TTS model.

### Execution Modes

| Mode | Lifecycle | Advantage | Cost | Initial use |
| --- | --- | --- | --- | --- |
| Resident, compute-serialized | Keep Whisper and the selected LLM in VRAM, but permit only one heavy inference operation at a time | Lowest turn latency; no repeated model load | Combined resident VRAM must fit | Preferred for Whisper plus Gemma 1B/4B after measurement |
| Strict temporal swap | Load Whisper, transcribe, unload it, then load the LLM and generate | Allows combinations whose weights cannot coexist | Model-switch delay and storage/page-cache traffic on every voice turn | Fallback for larger text models |
| CPU/GPU split | Run speech recognition on CPU and the LLM on GPU | Avoids shared VRAM and GPU contention | Higher CPU use and usually slower transcription | Portable fallback and comparison profile |

Resident does not mean concurrent compute. Two CUDA processes can retain allocations while the
application-level coordinator serializes their expensive work:

```text
IDLE -> LISTENING -> TRANSCRIBING -> THINKING -> RESPONDING -> IDLE
```

The coordinator must reject overlapping `TRANSCRIBING` and `THINKING` states for the initial
single-GPU profile. This keeps latency predictable and avoids Whisper and llama.cpp competing for
memory bandwidth. Audio capture can continue into a bounded buffer, but a second transcription or
generation job waits behind the active operation.

### RTX 5070 Planning Envelope

Whisper Large v3 has 1.55B parameters. The standard whisper.cpp large-family artifact is about
2.9 GiB on disk and documents roughly 3.9 GB of runtime memory before host-specific CUDA variance.
For planning, reserve approximately 3.9–5.0 GiB while it is resident.

| Resident combination | Projected combined VRAM | Assessment |
| --- | ---: | --- |
| Whisper Large v3 + Gemma 3 1B Q4 | 5.2–7.0 GiB | Comfortable |
| Whisper Large v3 + Gemma 3 4B Q4 at 8K | 7.5–10.0 GiB | Feasible; requires a measured 1 GiB safety margin |
| Whisper Large v3 + Llama 3.1 8B Q4 at 8K | 11.2–14.1 GiB | Do not co-reside; use temporal swap |
| Whisper Large v3 + Gemma 3 12B Q4 | 11.9–14.6 GiB | Do not co-reside; use temporal swap |

Whisper Large v3 Turbo is the preferred first interactive candidate. It is a pruned Large v3 with
809M parameters and four decoder layers instead of 32; its publisher describes substantially
faster decoding with a minor quality reduction. Full Large v3 remains the quality comparator.
Neither is accepted until measured on Turkish and English speech, silence, background noise,
accents, technical vocabulary, and hallucination cases.

References:

- [OpenAI Whisper Large v3 model card](https://huggingface.co/openai/whisper-large-v3)
- [OpenAI Whisper Large v3 Turbo model card](https://huggingface.co/openai/whisper-large-v3-turbo)
- [whisper.cpp CUDA, memory, quantization, VAD, and local-runtime documentation](https://github.com/ggml-org/whisper.cpp)

### Service and Data Boundaries

- Run speech recognition as a separate local service; it is not part of llama.cpp's text-model LRU.
- Give the voice coordinator one GPU-operation semaphore shared with generation.
- Bound audio duration, size, format, sample rate, queue depth, and request timeout.
- Treat the transcript as untrusted user input and pass it through the normal chat authorization,
  validation, retrieval, and prompt-injection boundaries.
- Default to ephemeral audio: process it, retain only required operational metrics, and delete the
  recording unless the user explicitly requests storage.
- Require visible microphone/recording consent and never activate capture implicitly.
- Record speech model/revision, detected or requested language, audio duration, real-time factor,
  word-error evaluation result, peak RAM/VRAM, and whether temporal swapping occurred.
- Keep all inference local. There are no per-request API charges; operational costs are disk,
  electricity, model acquisition time, and local compute.

This should be planned as a dedicated voice work package after the core Phase 5 model-adaptation
work, with its own runtime build, model manifest, API contract, browser microphone flow, resource
benchmark, bilingual quality suite, privacy behavior, and acceptance record.
