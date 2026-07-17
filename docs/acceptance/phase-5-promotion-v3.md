# Phase 5 v3 Adapter Promotion Decision

Date: 2026-07-17

Adapter: `gemma3-1b-lora-v3-production-contract-r16-lr0.0002-f47e1ce07bb9`
Decision: **rejected; base-only runtime remains the default**

## Outcome

The corrective v3 run trained for 180 optimizer updates on 600 production-prompt examples. Its
separate 240-case development proxy passed with behavior score `0.8611`; PEFT-to-GGUF parity also
passed with token F1 `0.8234` and runtime behavior score `0.8637`. These results accepted the
training/export/runtime path, not production promotion.

The strict production matrix failed 11 gates. Adapter+RAG behavior achieved language adherence
`1.0000` and JSON validity `1.0000`, but citation-format validity was `0.7000`, incident structure
`0.5000`, terminology consistency `0.5000`, and supported refusal `0.5000`.

On the protected 40-case corpus, the adapter recorded fact coverage `0.6406`, citation accuracy
`0.4375`, citation coverage `0.8125`, faithfulness `0.4375`, hallucination `0.5625`, refusal accuracy
`0.5000`, and zero restricted-fact leaks. Mean/P95 TTFT (`48.1/56.6 ms`) also exceeded the reusable
fresh-base result (`36.6/43.8 ms`) by more than 20%.

## Evidence

The strict matrix is `var/training/wp5.5-v3/evaluation-matrix.json`, SHA-256
`5919a6ddcd250fa00ba93c75ae20c6a5f061d2cd7b4ef3b36977d962a53c9fe3`.
The nine-artifact index is `var/training/wp5.5-v3/evidence-index.json`, SHA-256
`4c1800dd02721665bcc5ef75db829f98ecd5346b9c909c59b80f549ad906d4d6`, and records
`promotion_passed: false`. The prior base reports were reused because the runtime build, model and
embedding revisions, prompt version, datasets, and generation settings were unchanged.

The v3 adapter is retained as reproducible negative evidence. Its runtime profile is opt-in and it
must not be configured as the default.

By project decision, Phase 5 closes with the base-only runtime rather than starting another adapter
iteration. The training and adapter infrastructure is accepted as a future extension point; model
quality work resumes only after the initial eight-phase barebones structure is complete.
