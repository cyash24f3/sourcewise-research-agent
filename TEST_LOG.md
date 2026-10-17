# Test log

All runs used real Gemini 3.8 Flash calls with a research date of 23 September 2026.
[Run results](submission/experiment_results.json) keep timings, usage and prompt hashes.

| Run | What happened | What changed |
|---|---|---|
| 1 | A quote changed a fiscal year. The 387-word draft also confused spending with funding. | Exact matching caught the quote. At the time, logged alignment allowed a restart. Tightened the financial wording. |
| 2 | More copying errors. The 435-word draft missed the business description and overstated contract risk. | Added copying, business coverage and inference rules. This run also resumed after logged alignment. |
| 3 | A fresh run produced 361 words. Review found unsupported product wording and missing current pledge data. | Tightened business scope, margin wording and current-data coverage. |
| 4 | A new writer call reused the reviewed ledger and produced 314 words. | Shortened the brief. This was the earlier submission. |
| 5 | The stricter checks caught a missing date excerpt, then blocked unsupported date expansions in the draft. Inspection also found a guessed cause for the revenue conflict. | Added table-header quotes and exact date wording. Extended model review to source decisions and conflict explanations. |
| 6 | A fresh run corrected one missing date excerpt, then passed all three stages. The 265-word brief still omitted current pledging. | Made current pledge coverage explicit and clarified financial terms. |
| 7 | Reused the checked evidence from run 6 and made new writing and review calls. All checks passed. | Selected this 269-word brief. This is the run in the recording. |

The audit also found that fuzzy quote repair could let the wrong metric pass when
its number appeared elsewhere in a source. That repair path is removed. The agent
now allows one explicit model correction and keeps both replies.

A separate live probe used revenue of 100 and capex of 900 in one exact quote.
The wrong claim, revenue of 900, passed numeric matching but the new model review
rejected it. Offline tests also check that a rejected review cannot export a brief.

The final brief has no hand edits. Original sources and verbatim quotes stay
unchanged. Model review is another check, not proof of accuracy.
