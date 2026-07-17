# Phase 5 Adapter Export and Runtime Acceptance

Date: 2026-07-17

Work package: 5.4
Outcome: runtime integration accepted; production promotion remains blocked

## Artifact identity

- Adapter: `gemma3-1b-lora-v2-data-schedule-r16-lr0.0002-2cfa8faead45`
- PEFT weights SHA-256: `3b2672643360d76b7e28f2683f43da5d39b52650c21f9126869c75bdcb6dba87`
- GGUF adapter SHA-256: `3a3700de507b6d038fca7392175905bab8852c0528169b6bbb022b80900dc80b`
- Immutable manifest SHA-256: `0834f8ca0e7236199d568f1611175c28beba3c16c44ec75089ca2de0a4cd0f82`
- llama.cpp revision: `c198af4dc24f8e0ab8a569a60f931e03a192fd79`
- Converter SHA-256: `3c5f109f3d7a5ef530ea388d8e994512df6f544ce1aa8b2e39be446223637b93`
- Runtime base: `ggml-org/gemma-3-1b-it-GGUF:Q4_K_M`

All nine files in the exported package matched the sizes and SHA-256 values in the manifest. The
GGUF file has a valid GGUF v3 header. Export validation rejected unsupported modules, non-LoRA or
unpaired tensors, trainable embeddings/tokens, DoRA/RS-LoRA, and source/runtime base mismatches.

## Runtime contract

The base-only profile is `config/models/gemma3-1b-base.env`. The opt-in adapted profile is
`config/models/gemma3-1b-v2-adapter.env`. Adapter startup requires a readable GGUF and immutable
manifest, exact SHA-256, matching adapter ID/file identity, compatible accepted runtime base, and a
non-negative scale. Missing, corrupt, identity-mismatched, and base-incompatible inputs stop before
server launch with an actionable error.

The API exposes `adapter_id` and `adapter_sha256` through `/health/llm` and `/health/runtime`.
Production evaluation modes now accept `base`, `base_rag`, `adapter`, and `adapter_rag`; adapter
modes require an adapter identity, while base modes reject an adapted runtime identity.

## Live compatibility and parity

llama.cpp loaded the base and adapter at scale `1.0`. Its `/lora-adapters` response identified slot
`0`, the exact GGUF path, and scale. The same 120 development held-out cases used by the PEFT
evaluation were then run through the deployed GGUF adapter with greedy decoding.

| Measure | PEFT | Deployed GGUF | Delta |
| --- | ---: | ---: | ---: |
| Language adherence | 1.000000 | 1.000000 | 0.000000 |
| Task validity | 1.000000 | 0.991667 | -0.008333 |
| Mean expected-answer token F1 | 1.000000 | 0.998380 | -0.001620 |
| PEFT/GGUF output token F1 | — | 0.998380 | — |
| Exact output match | — | 0.983333 (118/120) | — |

The deployed report passed its compatibility thresholds. Its SHA-256 is
`345c6e1398574cd1b5d8208b5cb8ee1e923b2e271f077b46e4716ad5068e52ff`.

Two Turkish outputs drifted. One citation answer changed only wording and remained valid. One JSON
answer became labeled prose, reducing JSON task validity from `1.00` to `0.95`. This is acceptable
for WP5.4 compatibility but fails the eventual strict JSON promotion target.

## Rollback proof and decision

After the adapted run, the server was stopped and relaunched with the base-only profile. The
base-model ID, quantization, context, GPU offload, and runtime build were unchanged, while
`/lora-adapters` returned `[]`. No data migration or artifact mutation occurred.

WP5.4 is accepted. The adapter remains `promotion_eligible: false`; WP5.5 must run the untouched
four-mode behavior corpus and protected Phase 4 base+RAG versus adapter+RAG regression gates. The
deployed Turkish JSON drift is a known strict-gate risk, not an expected failure to waive.
