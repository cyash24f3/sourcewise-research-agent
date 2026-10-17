# SourceWise Research Agent

A small Python agent that turns an NSE ticker and supplied documents into a concise,
cited research brief: **Snapshot, Bull case, Bear case, Open questions, Sources**.
It uses Google's official `google-genai` SDK directly, without an agent framework.

## Run it

Python 3.10+ is supported; development uses Python 3.12. Install
[uv](https://docs.astral.sh/uv/), then from the project directory:

```bash
uv sync --extra dev
cp -n .env.example .env
# Set GEMINI_API_KEY in .env. Never commit or share the key.
uv run research run --ticker SRVCABLE --company "Sarvottam Cables Ltd" \
  --docs research_pack --as-of 2026-09-23
```

The command prints the path to `artifacts/runs/<unique-run>/brief.md`. Supply
`--output-root /path/to/runs` to choose another directory. The as-of date is explicit:
this fictional assignment assumes **23 September 2026**, regardless of execution date.
The output is generated automatically; the submission brief is not edited by hand.

For a local browser demo with a real API run:

```bash
uv run python scripts/demo_server.py
# Open http://127.0.0.1:8765
```

The viewer binds only to localhost. `/record` captures the live application's canvas
for 2 minutes 20 seconds, with explanatory captions and no microphone or desktop
capture. It saves `submission/demo.webm`. The recording shows real CLI/API execution,
one design decision, and a limitation. It contains no fixture model response.

## Design

1. **Ingest:** validate UTF-8 Markdown/text and YAML metadata, preserve original
   checksums, assign source IDs, and exclude documents published after the research date.
2. **Assess and extract:** a model call classifies every source as `use`,
   `context_only`, or `exclude`; it extracts facts, management expectations, and
   conflicts with source excerpts. Instructions in documents remain untrusted data.
3. **Validate evidence:** reject invalid schemas, unknown/excluded sources,
   unsupported numeric quantities, and quotations absent from their cited documents.
4. **Write:** another model call writes a short brief from the ledger, referencing
   fact IDs and conflict IDs. Python builds citations from original source metadata.
5. **Save:** retain prompts, inputs, schemas, original responses, receipts, structured
   evidence, validation results, and Markdown. Failures are retained rather than hidden.

Separate system prompts are in `src/research_agent/prompts/`. Active prompts are
`evidence_v4.md` and `writer_v4.md`; earlier versions are preserved for the test log.

### Quote alignment

Models sometimes copy a long excerpt with a small character error. The program can
replace such an excerpt with its **unique original source paragraph** when at least
94% of the proposed quote's characters align and the paragraph is at most three
times its length. Quotes under 80 characters, ambiguous candidates, unknown sources,
and excluded sources are not repaired. Claims and source IDs never change.
`quote_alignment.json` records the original quote, exact replacement, and score.
The original API response remains unchanged. Exact-quote and numeric checks run
again afterward; an alignment is not proof that the claim follows from the passage.

Two early full-run attempts were resumed from their original extraction responses
using this deterministic policy, then passed through the real writer API. Their
initial failures and resumed stages are retained separately. See `TEST_LOG.md`.

## Model choice

The selected model is **Gemini 3.8 Flash** (`gemini-3.8-flash`), used for both stages
through the Interactions API with JSON-schema output and medium reasoning. It was
chosen for the requested free-tier workflow, document context, structured output,
and speed. A high-reasoning extraction spent most of its budget thinking and returned
incomplete JSON; medium reasoning left room for the actual evidence output.

The model is explicit; there is no silent provider fallback. API keys are read from
`.env` or process environment and excluded from Git and artifacts. `GEMINI_API_KEY`
(or `GOOGLE_API_KEY`) is required; `GEMINI_MODEL` must match the selected model.
Free quota and continued availability depend on the Google project; this program
never enables billing or guarantees future quota.

## Useful commands

```bash
uv run research check
uv run research config
uv run research test-api
uv run research inspect --docs research_pack --as-of 2026-09-23
uv run research extract --ticker SRVCABLE --company "Sarvottam Cables Ltd" \
  --docs research_pack --as-of 2026-09-23
uv run research run --help
```

`inspect` and `check` make no model request. `config` reports key presence, never the
key itself. `test-api` makes a small live acknowledgement request. `run` makes two
logical requests; transport errors have one bounded retry layer (at most three
HTTP sends per request). Authentication/access failures stop immediately. Each
research request has a 180-second timeout per attempt. There is no automatic
semantic retry loop. `--writer-version writer_v1|writer_v2|writer_v3|writer_v4` supports the
recorded experiments. `--evidence-run <directory>` reuses saved evidence only after
checking the target, company, date, and document hashes and revalidating its ledger.

Each input file needs YAML front matter:

```markdown
---
source: Example company filing
url: https://example.com/results
published: 2026-09-20
type: official company filing
---
Document text goes here.
```

Nested `.md` and `.txt` files are supported. Hidden files and unsupported formats
are ignored. Invalid metadata, duplicate keys, bad dates/URLs, symlinks, empty input,
non-UTF-8 text, and oversized files fail clearly. Limits: 100 KB/file and 500 KB/pack.
URLs are citation labels and are never fetched. This is a supplied-document agent;
it has no browsing tool or live market feed.

## Validation and limitations

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
```

Tests are offline, including actual-SDK mocked HTTP tests. They cover ingestion,
future exclusion, prompt separation, credential redaction, retry bounds, evidence,
quote alignment, citation IDs, numeric support, brief limits, and failure retention.

Quote matching proves provenance, **not truth or semantic entailment**. A quote can
be misinterpreted, source assessment can be wrong, and management claims need
attribution. Numeric checks verify presence, not units, relationships, arithmetic,
or calendar reasoning. The narrative is capped at 450 words; prompts aim for a
shorter final brief. Markdown pagination depends on the viewer. The agent does not
provide buy/sell ratings, current prices, or a valuation model.

## Submission files

- `submission/SRVCABLE_brief.md`: exact final generated Markdown.
- `submission/form_answers.md`: ready-to-paste form answers and links.
- `TEST_LOG.md`: real experiments, outcomes, and design changes.
- `submission/runs/`: original responses and reproducibility evidence.
- `submission/demo.webm`: captioned live application recording (also shared on Drive).
- `MILESTONES.md`: progress and verification record.

The eight original research documents and assignment are preserved. The standalone
`assignment/README.md` is newer than the copy inside `candidate.zip`.
