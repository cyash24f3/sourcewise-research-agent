"""Brief generation, citation integrity, and failure retention with offline fixtures."""

import json
from datetime import date

import pytest

from research_agent import workflow
from research_agent.config import GeminiSettings
from research_agent.documents import Document, DocumentError
from research_agent.gemini import ConnectionReceipt
from research_agent.models import EvidenceLedger, ResearchBrief
from research_agent.render import render_markdown
from research_agent.validation import ValidationFailure, validate_brief


@pytest.fixture
def data():
    ledger = EvidenceLedger.model_validate(
        {
            "source_decisions": [
                {"source_id": "S01", "disposition": "use", "reason": "Primary filing"},
                {"source_id": "S02", "disposition": "context_only", "reason": "Conflict"},
            ],
            "facts": [
                {
                    "fact_id": "F01",
                    "kind": "reported",
                    "claim": "Revenue was ₹100 crore.",
                    "evidence": [{"source_id": "S01", "quote": "Revenue was ₹100 crore."}],
                }
            ],
            "conflicts": [
                {
                    "topic": "Revenue",
                    "source_ids": ["S01", "S02"],
                    "resolution": "Primary reports ₹100 crore; news reports ₹200 crore.",
                    "evidence": [
                        {"source_id": "S01", "quote": "Revenue was ₹100 crore."},
                        {"source_id": "S02", "quote": "Revenue was ₹200 crore."},
                    ],
                }
            ],
        }
    )
    brief = ResearchBrief.model_validate(
        {
            "snapshot": [{"text": "Revenue was ₹100 crore.", "fact_ids": ["F01"]}],
            "bull_case": [{"text": "Revenue supports business scale.", "fact_ids": ["F01"]}],
            "bear_case": [{"text": "Revenue quality needs scrutiny.", "fact_ids": ["F01"]}],
            "open_questions": [
                {
                    "text": "Why do ₹100 crore and ₹200 crore differ?",
                    "fact_ids": [],
                    "conflict_ids": ["C01"],
                }
            ],
        }
    )
    docs = [
        Document(
            f"S{i:02}",
            f"{i}.md",
            f"Source {i}",
            f"https://example.com/{i}",
            "2026-09-20",
            "test",
            f"Revenue was ₹{100 * i} crore.",
            str(i),
            20,
        )
        for i in (1, 2)
    ]
    return ledger, brief, docs


def test_conflict_citations_include_both_sources(data):
    ledger, brief, docs = data
    validate_brief(brief, ledger)
    result = render_markdown(brief, ledger, docs, "EXAMPLE", None, date(2026, 9, 23))
    assert "differ? [S01](#source-s01) [S02](#source-s02)" in result
    assert '<a id="source-s02"></a>' in result
    assert "https://example.com/2" in result


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_fact",
        "unknown_conflict",
        "no_evidence",
        "invented_number",
        "url",
        "too_long",
        "empty_section",
    ],
)
def test_brief_rejects_untraceable_or_oversized_output(data, mutation):
    ledger, brief, _ = data
    if mutation == "unknown_fact":
        brief.snapshot[0].fact_ids = ["F99"]
    elif mutation == "unknown_conflict":
        brief.open_questions[0].conflict_ids = ["C99"]
    elif mutation == "no_evidence":
        brief.snapshot[0].fact_ids = []
    elif mutation == "invented_number":
        brief.snapshot[0].text = "Revenue was ₹999 crore."
    elif mutation == "url":
        brief.snapshot[0].text = "See https://invented.example"
    elif mutation == "too_long":
        brief.snapshot[0].text = "words " * 451
    else:
        brief.bear_case = []
    with pytest.raises(ValidationFailure):
        validate_brief(brief, ledger)


def test_reused_evidence_is_revalidated_and_original_response_preserved(
    data, tmp_path, monkeypatch
):
    ledger, brief, docs = data
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "input.json").write_text(
        json.dumps(
            {
                "ticker": "EXAMPLE",
                "company": None,
                "as_of": "2026-09-23",
                "documents": [doc.as_dict() for doc in docs],
            }
        )
    )
    (evidence / "ledger.json").write_text(ledger.model_dump_json())
    (evidence / "run.json").write_text('{"prompt_version": "fixture"}')
    monkeypatch.setattr(workflow, "load_documents", lambda *args: (docs, []))
    original = brief.model_dump_json()
    calls = []

    def generate(settings, **kwargs):
        calls.append(kwargs)
        return ConnectionReceipt(
            "now",
            "fixture",
            "gemini-3.8-flash",
            "gemini-3.8-flash",
            "test",
            original,
            0.1,
            1,
            100,
            100,
            0,
            200,
        )

    monkeypatch.setattr(workflow, "generate_text", generate)
    result = workflow.run_research(
        GeminiSettings("offline", "test"),
        ticker="EXAMPLE",
        company=None,
        docs_dir=tmp_path / "docs",
        as_of=date(2026, 9, 23),
        output_root=tmp_path / "runs",
        writer_version="writer_v1",
        evidence_run=evidence,
    )
    assert (result.directory / "response.txt").read_text().strip() == original
    assert json.loads((result.directory / "run.json").read_text())["status"] == "complete"
    assert not json.loads((result.directory / "run.json").read_text())["fresh_extraction"]
    assert len(calls) == 1
    assert calls[0]["schema"] == ResearchBrief.model_json_schema()
    assert "C01" in json.loads(calls[0]["prompt"])["conflict_ids"]


def test_output_cannot_overwrite_sources(tmp_path):
    with pytest.raises(DocumentError, match="outside"):
        workflow.run_research(
            GeminiSettings("offline", "test"),
            ticker="EXAMPLE",
            company=None,
            docs_dir=tmp_path,
            as_of=date(2026, 9, 23),
            output_root=tmp_path / "runs",
        )
