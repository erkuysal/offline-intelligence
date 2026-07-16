# Phase 5 Evaluation Matrix

Status: In progress

Work Package 5.2 compares four explicit modes:

| Mode | Adapter | RAG |
| --- | --- | --- |
| `base` | No | No |
| `base_rag` | No | Yes |
| `adapter` | Yes | No |
| `adapter_rag` | Yes | Yes |

The decisive promotion comparison remains `base_rag` versus `adapter_rag`. The other two modes are
diagnostic controls.

## Implemented Contract

- Evaluation cases can label any of the six Phase 5 tasks and declare JSON, incident-section, and
  terminology expectations.
- Generation results retain the Phase 4 quality, safety, and performance metrics and add language
  adherence, citation-format validity, JSON-schema validity, incident-report structure,
  terminology consistency, and supported refusal.
- The matrix reports task measures globally and reports quality, safety, and performance metrics by
  language and task. The aggregate report does not duplicate per-case answers or source text.
- Public datasets may retain reviewable per-case answers. Restricted datasets are schema-gated to
  `redacted`; their reports retain scores and diagnostics but persist no answer text.
- Inputs must contain identical dataset identities and case IDs. Mode labels are embedded in each
  source report rather than inferred from filenames. Adapter modes require an adapter ID.
- A configured task threshold that is missed or was not measured fails the matrix and causes the
  CLI to return status `1`. Task thresholds gate `adapter_rag` by default; diagnostic modes remain
  visible without becoming promotion blockers. `--gate-mode` can explicitly select additional
  modes. Invalid or inconsistent inputs return status `2`.
- Generic natural-answer thresholds embedded in behavior-corpus reports remain visible as source
  diagnostics but do not gate the behavior matrix. JSON, incident, terminology, citation-format,
  refusal, and language behavior is gated by its task-specific measure.
- A separate pair of `base_rag` and `adapter_rag` reports on the protected Phase 4 regression corpus
  enforces the Phase 4 floor, Phase 5 promotion targets, and 20% relative TTFT, end-to-end latency,
  and throughput limits. Reusing the behavior corpus as the regression corpus is rejected.
- `training-evaluation-index` keeps dataset validation, training-run, held-out matrix, four behavior
  runtime reports, and two regression runtime reports as separate checksum-addressed artifacts. It
  cross-checks both evaluation identities, required modes, and adapter identity.

Assemble four completed reports with:

```bash
./manage.py training-evaluation-matrix \
  --base var/training/evaluation/base.json \
  --base-rag var/training/evaluation/base-rag.json \
  --adapter var/training/evaluation/adapter.json \
  --adapter-rag var/training/evaluation/adapter-rag.json \
  --base-rag-regression var/training/regression/base-rag.json \
  --adapter-rag-regression var/training/regression/adapter-rag.json \
  --min-language-adherence 1 \
  --min-citation-format-validity 1 \
  --min-json-schema-validity 1 \
  --min-incident-report-structure 1 \
  --min-terminology-consistency 1 \
  --min-supported-refusal 1
```

Matrix assembly is deterministic and does not contact an LLM server. Producing real
production-runtime input reports does require the applicable model runtime. RAG modes additionally
require retrieval; fresh dense retrieval requires the embedding service. The evaluator now runs
verified `base` and `base_rag` modes:

```bash
./manage.py evaluate-generation \
  --mode base \
  --dataset evaluation/datasets/phase-5-behavior-v1.jsonl \
  --output var/training/evaluation/base.json

./manage.py evaluate-generation \
  --mode base_rag \
  --dataset evaluation/datasets/phase-5-behavior-v1.jsonl \
  --output var/training/evaluation/base-rag.json
```

The base run needs the generation server only. The base + RAG run also needs PostgreSQL and the
embedding server. Adapter modes remain unavailable until the adapter runtime boundary can verify
the active adapter ID rather than trusting a caller-provided label.

The checked-in `phase-5-behavior-v1` corpus contains twelve synthetic public cases, balanced across
English/Turkish and the six tasks. It shares no exact question or passage text with the protected
Phase 4 corpus and is always rejected as training provenance even if a training manifest omits it
from its reserved-path list.

The protected Phase 4 `dense-baseline-v1` corpus remains the natural-answer regression and
promotion corpus. Its base + RAG and adapter + RAG reports use identical cases and retain the
generic fact, citation, faithfulness, refusal, leak, and runtime gates. Phase 5 structured behavior
results never substitute for that regression evidence.

Language adherence uses a deterministic English/Turkish lexical and character signal. It is useful
as an automated regression gate for this bounded corpus, but ambiguous short outputs still require
per-case review and must not be treated as general-purpose language identification.

Build the final evidence index after training and all runtime reports exist:

```bash
./manage.py training-evaluation-index \
  --dataset-validation var/training/data-validation.json \
  --training-run training/runs/<run-id>/training-report.json \
  --held-out-behavior var/training/evaluation-matrix.json \
  --runtime var/training/evaluation/base.json \
  --runtime var/training/evaluation/base-rag.json \
  --runtime var/training/evaluation/adapter.json \
  --runtime var/training/evaluation/adapter-rag.json \
  --regression-runtime var/training/regression/base-rag.json \
  --regression-runtime var/training/regression/adapter-rag.json
```

The training-run report must declare `report_type: training_run`, a passing result, training dataset
ID/version/checksum, and adapter ID. Work Package 5.3 will produce that report; Work Package 5.2
defines and tests its evidence boundary without fabricating a completed training run.

## Recorded Runtime Progress

On 2026-07-16, the real pinned GGUF base runtime completed the twelve-case `base` diagnostic. The
report is stored locally at `var/training/evaluation/base.json`. It recorded parse success `1.0`,
fact coverage `0.05`, citation accuracy/coverage `0.0/0.0`, refusal accuracy `0.0`, zero restricted
fact leaks, mean/P95 TTFT `67.3/84.3 ms`, and `54.8` tokens/s. Poor grounded behavior is expected
without retrieved context; this diagnostic is not a promotion candidate.

The matching `base_rag` run completed after PostgreSQL became available. Its local report is
`var/training/evaluation/base-rag.json`. It recorded fact coverage `0.75`, refusal accuracy `1.0`,
zero restricted leaks, mean/P95 TTFT `197.5/247.2 ms`, and `43.5` tokens/s. Its generic
natural-answer diagnostics recorded citation accuracy `0.60`, citation coverage `0.6343`,
faithfulness `0.52`, hallucination rate `0.48`, and P95 end-to-end latency `3419.0 ms`. Those misses
remain expected unadapted-model diagnostics, but they are not treated as Phase 4 floor failures on
this structured behavior corpus. JSON validity, incident structure/citation behavior, terminology,
language, and supported refusal remain task-gated. The model servers were stopped after the run;
PostgreSQL remains available for development and tests.

The corrected protected regression run is stored locally at
`var/training/regression/base-rag.json`. On the forty-case Phase 4 corpus, the same base + RAG
runtime passed every protected floor: parse success `1.0`, fact coverage `0.703`, citation
accuracy/coverage `0.688/0.750`, faithfulness/hallucination `0.688/0.312`, refusal accuracy `1.0`,
zero restricted leaks, mean/P95 TTFT `479.1/632.1 ms`, mean/P95 end-to-end latency
`946.1/1467.3 ms`, and `20.8` tokens/s. This confirms that the Phase 5 behavior misses are expected
unadapted structured-task gaps rather than a regression of the accepted natural-answer RAG floor.

## Remaining Work

- Reuse the live evaluator for all four modes without allowing callers to mislabel runtime state.
