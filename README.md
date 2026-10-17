# SourceWise Research Agent

A Python agent that takes an NSE ticker and supplied documents and produces a
cited brief: Snapshot, Bull case, Bear case, Open questions, and Sources.

## Run

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
cp -n .env.example .env
# Add GEMINI_API_KEY to .env.
uv run research run --ticker SRVCABLE --company "Sarvottam Cables Ltd" \
  --docs research_pack --as-of 2026-09-23
```

The command prints the path to the generated `brief.md` under `artifacts/runs/`.
The fictional test case uses 23 September 2026 as the research date.

For the local browser demo:

```bash
uv run python scripts/demo_server.py
# Open http://127.0.0.1:8765
```

## Model and design

The agent uses **Gemini 3.8 Flash** through the official Google Python SDK and
Interactions API, with structured JSON output and medium reasoning. The model was
selected for the free-tier workflow, document context, and speed. Free quota and
future availability depend on the Google project.

One call assesses sources and extracts quoted evidence. Another writes from that
evidence. Python checks references, quotations, numbers, dates, and length, then
builds citations from original source metadata. Instructions embedded in documents
are treated as untrusted data.

Long quotes with small copying errors can be aligned to one unique original source
paragraph when character coverage is at least 94%. Changes are logged; claims and
source IDs stay unchanged. These checks establish provenance, not source truth or
complete semantic support. There is no live market feed or valuation model.

Separate system prompts:

- [Evidence assessment](src/research_agent/prompts/evidence_v4.md)
- [Brief writing](src/research_agent/prompts/writer_v4.md)

## Evaluation

- [Generated SRVCABLE brief](submission/SRVCABLE_brief.md), with no hand edits.
- [Three-run test log](TEST_LOG.md) and [run results](submission/experiment_results.json).
- [2-minute-20-second demo](https://drive.google.com/file/d/17gT_gOsWWC8RmR1kozjdQ9QOLTF2NcjY/view):
  captioned live application recording showing experiment 3, a design decision,
  and a limitation. The final brief followed an additional writing pass.
- `research_pack/` contains the eight original input documents.

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
```

The tests run offline. API keys belong in `.env`, which is excluded from Git.
