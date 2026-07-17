# Fine-Tuning Post-Mortem: v3 Production-Contract Transfer Failure

## Executive summary

V3 fixed the literal production prompt, citation-label, JSON-schema, and incident-heading mismatch,
but did not generalize reliably to the small untouched production behavior set or protected natural
answers. The remaining limitation is not GGUF conversion: PEFT/GGUF parity passed. It is a mixture
of over-optimization, asymmetric task transfer, false refusal, and a development proxy that was
still easier than production despite being independently authored.

## Relevant outcomes

- Validation loss was best at step 20 (`0.3455`) and rose monotonically to `0.6340` at step 180.
  The constant learning rate continued updating after the best validation point; no step-20 adapter
  checkpoint existed, so the bounded final artifact was evaluated.
- Early pre-clipping gradient norms reached `12.7–14.9` against max norm `2.0`. Norms later collapsed
  to roughly `0.001–0.004`, consistent with large early movement followed by saturation.
- Independent development passed overall (`0.8042` task validity), but English validity was
  `0.9750` versus Turkish `0.6333`. Grounded answer (`0.5750`) and terminology (`0.6250`) were weak
  even before export; aggregate thresholds allowed the candidate to proceed for runtime testing.
- GGUF behavior closely matched PEFT (`0.8234` parity F1, validity delta `+0.0125`). Quantization and
  conversion are therefore not the primary failure source.
- Production adapter+RAG preserved JSON validity (`1.0`) but failed citations, incident structure,
  terminology, and refusal. English incident/terminology structure fell to `0.0`, while Turkish
  supported refusal fell to `0.0`, showing task-language interference rather than one global defect.
- Protected citation coverage improved over the reused base (`0.8125` versus `0.7188`), but citation
  accuracy and faithfulness fell to `0.4375`; the model emitted more citation-shaped output without
  reliably attaching it to supported claims.

## Technical interpretation

The 600-example corpus multiplied scenarios but retained only a few response programs per
task/language. The model learned strong surface contracts—especially exact JSON and refusal text—yet
overfit correlations between language, instruction layout, and response type. In Turkish grounded
answers it frequently selected the refusal policy even when a relevant source was present. In
English structured tasks it often paraphrased required headings instead of emitting them literally.

The independent development set prevented exact example leakage, but shared the same source grammar,
task decomposition, and response construction module. Different names and vocabulary did not create
enough distribution distance. Its overall threshold also allowed strong JSON and refusal cells to
mask weak grounded-answer, terminology, and Turkish slices.

## Recommended next research

1. Add per-language/per-task development gates; do not accept an aggregate pass when any supported
   cell is below its production-relevant minimum.
2. Save/evaluate every validation checkpoint and use behavior-aware early stopping. Test 20–60
   updates before another 180-step run.
3. Replace scenario multiplication with independently authored prompt/source/output families,
   including adversarial relevant-vs-missing evidence pairs that differ by only one source fact.
4. Add contrastive cases for false refusal, literal headings versus prose headings, and citation
   presence versus citation correctness.
5. Score citation entailment during development, not only label syntax; higher coverage coexisted
   with lower accuracy and faithfulness here.
6. Keep development authoring code separate from the training generator and use bootstrap intervals
   once every task/language cell is sufficiently large.

No v3 model should be promoted or made default. Further training should wait until the development
gate and early-checkpoint selection methodology are corrected.
