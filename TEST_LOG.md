# Test log

SRVCABLE · research date 2026-09-23 · execution date 2026-10-17 · Gemini 3.8 Flash.
These experiments used real API calls. Timings, token usage, prompt hashes, and
validation results are in [experiment_results.json](submission/experiment_results.json).

| Run | What went wrong | Change and outcome |
|---|---|---|
| 1 | A fiscal year changed inside a quotation. The resulting 387-word brief also blurred capex spending with funding. | Exact-quote validation stopped extraction. Added logged alignment to one original source paragraph, resumed extraction, and made a writer call. Tightened the financial wording for later prompts. |
| 2 | Two more copying errors; the 435-word brief omitted the business description and inferred that remaining contracts lacked protection. | Used stricter copying instructions and simpler writing. Resumed after logged quote alignment, then made a new writer call. Added explicit coverage and inference rules. |
| 3 | A fresh two-stage run produced 361 words. Checks passed, but review caught unsupported product wording, broad profit language, and omitted current pledging. | Tightened business scope, margin-versus-profit wording, and current-pledge coverage. This is the run shown in the recording. |

A final writing pass used the complete, previously reviewed evidence ledger with
writer v4 and produced the **314-word submission brief**. It reused evidence and
made a new writer call; it was not another fresh extraction. No narrative was
edited by hand. Current prompts are in `src/research_agent/prompts/`.

Quote matching and numeric presence do not prove a correct interpretation. That
limitation remains relevant even when all automated checks pass.
