# SourceWise Research Agent

Give the agent an NSE ticker and a folder of documents. It writes a short brief
with a Snapshot, Bull case, Bear case, Open questions and Sources.

## Run

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --frozen --extra dev
cp -n .env.example .env
# Add GEMINI_API_KEY to .env.
uv run research run --ticker SRVCABLE --company "Sarvottam Cables Ltd" \
  --docs research_pack --as-of 2026-09-23 --export-dir submission
```

The export contains the brief and its evidence. Full replies, checks and API
receipts stay under `artifacts/runs/`. The eight original inputs are in
`research_pack/`. SRVCABLE is fictional; the research date is 23 September 2026.

## How it works

Three Gemini calls read the sources, write from quoted facts, then check every
fact and brief point against the original files. Python checks exact quotes,
numbers, references, dates and length. A failed quote check allows one logged
model correction. The program never repairs a quote by fuzzy matching.

Source links open the actual input files. Conflicts keep both sides; current
filings take priority over old reports. Promotional instructions and unrelated
companies are excluded. Forecasts stay conditional.

The model is **Gemini 3.8 Flash**, used directly through the official Google SDK
and Interactions API. I chose it for speed, structured output and the free tier.
Quota and future availability depend on the Google project.

The extra review can still miss an error. These checks do not prove that a source
is true. There is no live market feed or valuation model.

Separate system prompts: [read](src/research_agent/prompts/evidence_v5.md),
[write](src/research_agent/prompts/writer_v5.md),
[review](src/research_agent/prompts/review_v1.md).

## Review the result

- [Generated brief](submission/SRVCABLE_brief.md), with no hand edits.
- [Evidence and review](submission/evidence.json): source decisions, exact quotes,
  conflicts, claim checks and API receipts.
- [Test log](TEST_LOG.md) and [run results](submission/experiment_results.json).
- [Live demo](https://drive.google.com/file/d/17gT_gOsWWC8RmR1kozjdQ9QOLTF2NcjY/view):
  a captioned recording of the final writing and review calls using saved evidence
  from a fresh run. It covers one design choice and one limitation. No voice narration.

For the browser demo, run `uv run python scripts/demo_server.py` and open
[localhost](http://127.0.0.1:8765). A run needs your own API key.

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
```

The tests run offline. Keep the API key in `.env`; it is excluded from Git.
