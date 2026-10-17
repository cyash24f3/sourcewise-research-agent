# Assignment milestones

Build and review one milestone at a time. This file records actual completion;
draft code alone does not make a later milestone complete.

| # | Milestone | Status |
|---|---|---|
| 1 | Download and understand the assignment | Complete |
| 2 | Set up the Python project | Complete |
| 3 | Connect to the LLM API | Complete |
| 4 | Load the research documents | Complete |
| 5 | Assess sources and extract evidence | Complete |
| 6 | Generate the research brief | Complete |
| 7 | Validate output and handle failures | Complete |
| 8 | Run three experiments and improve it | Complete; three experiments plus final composition |
| 9 | Prepare the build for submission | Complete; public GitHub repository |
| 10 | Record the demo and prepare form answers | Complete; public recording and ready-to-paste answers |

## Milestone 1

Downloaded all ten files visible in the supplied Drive folder: the standalone
README, candidate ZIP, and eight research documents. `assignment/download_manifest.json`
records the nine standalone Markdown downloads, their Drive URLs, byte counts,
and SHA-256 checksums. The ZIP is preserved separately in `assignment/candidate.zip`.

The original source files have been copied into this project. The pack contains
conflicting financial figures, outdated information, an unrelated company,
promotional material, and embedded instructions that the agent must ignore.

## Milestone 2

Target directory: `/Users/cyash/PROJECTS/superteam`.

Completion criteria:

- Preserve the original assignment files.
- Install the Python package in an isolated environment with locked dependencies.
- Make the `research` console script and `python -m research_agent` work.
- Provide a local setup check that succeeds without API credentials.
- Verify the entry points and missing-project errors with smoke tests.

API requests, research outputs, and the assignment's three-run experiment log
belong to later milestones.

Verified on 2026-10-17:

- All nine standalone Markdown downloads match the recorded SHA-256 checksums.
- All eight research files are byte-for-byte identical to the copies in the ZIP.
- `uv sync --extra dev` installed the project into `.venv` using Python 3.12.13;
  `uv.lock` records the resolved dependency versions.
- `uv run research check` passes every local setup check.
- `uv run pytest -q` passes six smoke tests, including both entry points and
  execution outside the project directory.
- Ruff lint and formatting checks pass for `src` and `tests`.

At the end of Milestone 2, no LLM API requests had been made. No generated research
brief or three-run test log was claimed at that milestone.

## Milestone 3

Selected provider: Google Gemini Developer API.
Selected model: `gemini-3.8-flash`.

Implemented:

- Official `google-genai` SDK and its Interactions API; removed the unused OpenAI SDK.
- `.env` and process environment configuration, with the key hidden from settings
  representations, CLI output, errors, and receipt files.
- `research config` to inspect configuration without making an API request.
- `research test-api` to request a fixed acknowledgement and save a success receipt.
- A 30-second timeout per attempt and at most three HTTP attempts for transient
  failures, using a single retry layer. Permanent authentication, permission, and
  model-access errors stop immediately.
- Mocked-HTTP tests using the actual SDK, including a request-count regression test
  to prevent nested retries from wasting free quota.

Verified on 2026-10-17:

- All 25 offline tests pass; Ruff lint and formatting checks pass.
- The real `research test-api` command returned `GEMINI_CONNECTION_OK` from
  `gemini-3.8-flash` in 4.108 seconds, using one HTTP attempt and 22 total tokens.
- The success receipt is saved at
  `artifacts/api_checks/gemini-239d0395996a.json` (excluded from Git).

Billing-tier eligibility and future free quota availability cannot be established
by the connection test. The test did not enable or change billing. This connection
check does not count as one of the assignment's three research experiments.

## Milestone 4

Implemented:

- UTF-8 Markdown/text loading with required YAML source metadata; original byte
  checksums and byte counts are preserved.
- Clear input errors for invalid or ambiguous metadata, invalid dates/URLs,
  unsupported encodings, empty bodies, symbolic links, and oversized inputs.
- Explicit research-date filtering: sources published after the cutoff are
  reported separately and do not enter the eligible document list.
- Deterministic source IDs for a fixed filename inventory, independent of cutoff.
- `research inspect --docs ... --as-of ...` with readable and JSON output, plus
  an optional saved metadata manifest. This command does not use API credentials
  or call the model.

Verified on 2026-10-17:

- All eight original documents load successfully as of 2026-09-23; zero are future-dated.
- Their byte counts and SHA-256 checksums match the original download manifest.
- The local inspection manifest is saved at `artifacts/ingestion/manifest.json`.
- All 73 offline tests pass; Ruff lint and formatting checks pass.
- Tests cover same-day inclusion, future exclusion, future-only packs, invalid
  dates, duplicate YAML keys, malformed inputs, size limits, original-byte hashes,
  stable IDs across cutoffs, JSON output, and preventing source overwrites.

The old news article, promotional blog with embedded instructions, and unrelated
company article remain date-eligible. Their relevance, reliability, and treatment
as evidence will be assessed in Milestone 5. No LLM request was made for Milestone 4.

## Milestone 5

Implemented:

- Separate, packaged system prompts; the version used for Milestone 5 was
  `src/research_agent/prompts/evidence_v3.md`, with earlier versions preserved for comparison.
- `research extract` accepting a ticker, optional full company name, documents,
  research date, and configurable output root.
- Structured Gemini output for source decisions, reported facts, management
  expectations, inferences, conflicts, and historical updates.
- Exact excerpts required for facts and every source in a conflict. Excluded
  sources cannot be cited as evidence; future sources are not sent to Gemini.
- Reported numeric quantities are checked against cited source text, with ordinary
  numeric formatting allowed. Date interpretation and derived calculations remain
  outside this quantity-support check.
- Local schema/provenance validation, with failed runs retained for review and
  no validated ledger produced when checks fail.
- Unique audit folders containing the exact input, prompt and schema, original
  completed response, API receipt, validation results, structured ledger, and
  human-readable review.

Verified on 2026-10-17: 98 offline tests pass; Ruff lint and formatting checks pass.
The completed live extraction assessed all eight sources, extracted 15 supported
claims, and recorded two conflicts/updates. Inspection accepted the evidence for
brief generation, with separate review notes preserving the original model output.
All original source checksums still match; an artifact scan found no configured
API key in the saved text files.
Quote matching verifies provenance, not semantic entailment or source truthfulness.
The final brief and three complete research experiments remain later milestones.

Evidence-stage development so far:

1. The first request with v1, high reasoning, and a 12,000-output-token cap did not
   return a completed response. No ledger was accepted. The program was improved
   to preserve available incomplete-response diagnostics, and extraction was given
   a 20,000-output-token cap and a 180-second timeout per HTTP attempt.
2. The next v1 request completed in 89.675 seconds with 22 facts and two
   conflicts/updates. It used 20,607 total tokens (4,074 input, 4,141 output, and
   12,392 thought tokens), and every quoted excerpt matched a source. Inspection
   found speculation about a digit-transposition explanation and an unsupported
   date for a share-price move. The original output was preserved with review notes
   and marked `review_status: needs_revision`.
3. Version 2 explicitly prohibits speculative explanations and unsupported absolute
   dates, strengthens management attribution, and prioritizes 18 material facts.
   Its request completed in 79.418 seconds with 18 facts, two conflicts/updates,
   and 18,923 total tokens. Those earlier interpretation issues were corrected,
   but inspection found that F17 combined old and current pledge levels while
   citing only the old source. Its unchanged output was marked as needing revision.
4. Version 3 requires complete multi-source citation coverage. A new numeric-source
   check catches F17's missing support for 4.1%. A high-reasoning v3 request hit the
   20,000-output-token budget: 18,841 thought tokens left only 1,144 output tokens,
   resulting in incomplete JSON. Its partial text and usage were preserved; no
   ledger was accepted.
5. The same v3 prompt at medium reasoning completed in 61.168 seconds with one
   HTTP attempt and 15,197 total tokens (4,423 input, 3,381 output, and 7,393 thought
   tokens). All eight source decisions, 15 facts, and two conflicts/updates passed
   schema, exact-excerpt, and numeric-source checks. Four primary sources were
   selected, two secondary/historical sources retained as qualified context, and
   the promotional and unrelated-company sources excluded. Inspection found the
   earlier speculative explanation, unsupported event date, and incomplete pledge
   citations resolved. The run is saved at
   `artifacts/evidence/SRVCABLE-20261017T064330Z-dce62a6d/`, with separate review notes
   and `review_status: accepted_for_brief`. The GST-demand fact mixes a reported
   event with management's expected response; the brief must preserve that distinction.

These are development runs of the evidence stage, not the three complete research
brief runs required by the assignment.

## Milestones 6–10: completion sprint

- Implemented the two-stage `research run` workflow and separate writer prompts.
- Cited fact and conflict IDs are validated; source URLs come only from original metadata.
- Briefs are capped at 450 narrative words; the final prompt targets fewer words.
- Added numeric-presence checks and preserved failed runs and partial API diagnostics.
- Introduced auditable automatic alignment for long near-verbatim excerpts. It changes
  quotes only, requires one unambiguous source paragraph, and reruns evidence validation.
- Added a localhost demo viewer and a live application-surface recording with captions.
- 110 offline tests pass, with lint checks passing.
- `TEST_LOG.md` documents the real calls, two resumed experiments, and final fresh run.

Full semantic entailment remains a known limitation; exact quotations and numeric
presence cannot prove that a model interpreted every relationship correctly.

Final completion:

- Three real research experiments completed (two resumed after recorded quote failures),
  followed by a final writer_v4 composition using the complete reviewed evidence ledger.
- Final brief: 314 narrative words, unchanged from pipeline output; review notes and
  every selected run are in `submission/`.
- Build: https://github.com/cyash24f3/sourcewise-research-agent
- Recording: https://drive.google.com/file/d/17gT_gOsWWC8RmR1kozjdQ9QOLTF2NcjY/view
- Recording verified locally: 140.07 seconds, H.264 MP4, 1360 × 900, captioned live
  application-surface capture. It shows the third experiment; final composition followed.
- Drive permission readback confirms `anyone` / `reader`, undiscoverable by search.
- GitHub and the Drive recording opened in a signed-out browser.
- Form answers are prepared. No final form submission was made on the user's behalf.
