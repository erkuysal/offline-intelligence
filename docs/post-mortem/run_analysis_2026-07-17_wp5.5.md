# Run Analysis: WP5.5 Production Promotion Rejection

Date: 2026-07-17

Candidate: `gemma3-1b-lora-v2-data-schedule-r16-lr0.0002-2cfa8faead45`

## Executive summary

The candidate passed its 120-case generated development set and PEFT/GGUF parity check, but failed
the untouched production behavior and protected natural-answer RAG evaluations. The central problem
was not insufficient optimization. Training optimized a different message and output contract from
the deployed product. The adapter learned that synthetic contract strongly enough to interfere with
the base model's previously accepted RAG behavior.

## Technical findings

### 1. Citation grammar was not production-shaped

Training used markers such as `[doc-jade-archive-tr#p-047]`. The deployed prompt labels retrieved
chunks as `[Source 1]` and explicitly requires `[Source N]`. The dataset description called the
former production-shaped, but runtime evidence proves the grammars differ. This created negative
transfer: literal instructional text, malformed suffixes, and incomplete labels appeared.

Next experiment: render training context with the production context builder and use runtime
`[Source N: filename, chunk K]` labels plus their accepted `[Source N]` answer form.

### 2. Source placement differed between training and inference

Training placed synthetic source text inside the user message under a generic task system prompt.
Production places accessible context inside the system message and leaves the user message as the
question. This changes attention, instruction priority, refusal cues, and citation copying.

Next experiment: generate SFT messages by calling the production prompt builder. Store a prompt-
contract fingerprint with every rendered example.

### 3. Structured-output schemas did not match

Training JSON used `service/run_window/owner/status` or its Turkish equivalent. Promotion required
`status/interval_minutes/source` and `durum/aralik_dakika/kaynak`, including integers, enums, and
citation strings. Both JSON cases failed. Training incidents required
`Summary/Impact/Cause/Action`; production required `Impact/Timeline/Cause/Action`.

Next experiment: sample production-equivalent schemas and section sets. Validate all rendered
targets with production scorers before dataset admission.

### 4. Development held-out independence was structural, not behavioral

The 120 held-out cases came from the same generator, vocabulary, response templates, schema family,
and citation grammar as training. Unique `group_key` values prevented literal leakage but did not
group shared behavioral templates. Perfect development validity therefore measured interpolation
within the generator rather than transfer to the product contract.

Next experiment: group by normalized prompt/response contract, generator template, schema family,
and citation grammar. Never use the training-case generator for the decisive development set.

### 5. Natural-answer RAG behavior was omitted

The adapter saw no representative production natural-answer RAG distribution. On 40 protected
cases, fact coverage fell from `0.6719` to `0.3906`, faithfulness from `0.6562` to `0.4062`, and
hallucination rose from `0.3438` to `0.5938`. This is catastrophic interference, not a borderline
miss.

Next experiment: add a public production-contract replay/retention slice or use a two-objective
batch mixture. Gate intermediate checkpoints on a protected-style development proxy.

### 6. Turkish degradation remained hidden by synthetic parity

Adapter+RAG Turkish fact coverage was `0.3000` versus English `0.7333`; Turkish faithfulness was
`0.2000` versus `0.8000`. Two Turkish outputs switched to English. Equal example counts were not
enough because the English production system prompt and runtime source labels changed deployment.

Next experiment: include the English production system prompt paired with Turkish context/questions,
plus bilingual system variants. Gate every language/task cell.

### 7. The promotion set is a hard gate, not a precise estimator

The 12-case behavior corpus has one case per language/task cell. A single miss changes a task metric
by 0.5. It exposed severe failures but cannot compare small improvements.

Next experiment: expand the development proxy to at least 20 cases per language/task cell while
keeping the current corpus untouched as the final gate. Report bootstrap intervals.

### 8. Evaluator and evidence methodology needed repair

The production refusal parser omitted “do not have enough information,” although training accepted
it. After correction, refusal accuracy became `1.0000`; other failures remained. The evidence index
also rejected failed matrices. It now records `promotion_passed: false` without changing gates.

### 9. Runtime performance regressed

The adapter increased mean/P95 TTFT by roughly 37%/33% and mean end-to-end latency by about 23%.
Throughput fell about 19%, narrowly inside the relative limit. Future work should profile LoRA
application overhead and separate cold-cache from steady-state measurements.

## Recommended next run

Do not increase epochs or rank first. Build a production-contract dataset v3, validate every target
with production scorers, add natural-answer retention examples, and create an independently authored
development proxy. Start with rank 16 and the current optimization settings so data-contract effects
are isolated before another hyperparameter change.
