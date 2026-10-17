# Real experiment log

Company: Sarvottam Cables Ltd (NSE: SRVCABLE). Research date: **2026-09-23**.
Execution date: 2026-10-17. All calls used Gemini 3.8 Flash. Outputs are retained
exactly as returned; automatic quote alignment is recorded separately.
These are real API runs, not mocked test fixtures.

## Experiment 1 — baseline writer

- Extraction prompt: `evidence_v3.md`; writer: `writer_v1.md`.
- The initial extraction changed `FY2020-21` to `FY20-21` inside an otherwise
  near-verbatim quotation. Exact-quote validation rejected it and saved the failure.
- Design change: add deterministic alignment of long, near-verbatim quotations to
  one unique original source paragraph. This never changes claims or source IDs;
  it preserves original output and logs the replacement. Revalidation still applies.
- Resumed the saved extraction without another extraction call; made a real writer
  request. Completed brief: **387 words**, excluding Sources.
- Review: the brief was dense, repeated the revenue discrepancy, and blurred
  project spending progress with funding. It was not selected for submission.
- Preserved evidence: `submission/runs/experiment-1-extraction/` and
  `submission/runs/experiment-1-writer/`.

## Experiment 2 — copying discipline and retail clarity

- New extraction request with `evidence_v4.md`: fewer material facts, explicit
  character-for-character copying, and short contiguous excerpts. Writer changed
  to `writer_v2.md`: explain jargon and make questions actionable.
- Initial extraction still contained two quote-copy errors: a broken word and a
  paraphrased opening to the tax disclosure. The deterministic policy selected
  their unique source paragraphs; original failures remain in `initial_*` files.
- Resumed from that real extraction and made a new writer request. Completed brief:
  **435 words**, excluding Sources.
- Review: improved collection-language explanation, but still too long. Snapshot
  omitted the business description, and it inferred that the remaining contracts
  lacked protection. Appeal status also needed more careful wording.
- Preserved evidence: `submission/runs/experiment-2-extraction/` and
  `submission/runs/experiment-2-writer/`.

## Experiment 3 — compact, attributed final writer

- Fresh two-stage run from the original document pack, using `evidence_v4.md` and
  `writer_v3.md`. This is also the run shown in the demo recording.
- Writer changes: target 280–340 words, include the business in a short Snapshot,
  move the conflicting revenue figure to Open questions, preserve spending versus
  funding relationships, and forbid unsupported inverse-contract/appeal-status claims.
- Final metrics and review are recorded in `submission/runs/experiment-3/` and
  `submission/final_review.json` after completion.

## Earlier evidence-stage development

Before these full research experiments, the evidence stage was separately tested.
High reasoning exhausted the output budget; medium reasoning completed the ledger.
Inspection also caught a speculative explanation of a discrepancy, an unsupported
share-price event date, and a combined historical/current claim missing its second
source. Prompt versions and the detailed development history are in `MILESTONES.md`.
Those evidence-only requests are not counted as complete research experiments.

## Limits of the checks

Automated success establishes schema, evidence references, quote provenance,
numeric presence, and length constraints. It does not prove source truth or full
semantic entailment. Experiments 1 and 2 demonstrate why review is still necessary.
The final Markdown is copied directly from the pipeline; no narrative is hand-edited.
