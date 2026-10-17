"""Brief generation, citation integrity, and failure retention with offline fixtures."""

import json
from datetime import date
from urllib.parse import unquote

import pytest

from research_agent import workflow
from research_agent.config import GeminiSettings
from research_agent.documents import Document, DocumentError
from research_agent.gemini import ConnectionReceipt
from research_agent.models import EvidenceLedger, GroundingReview, ResearchBrief
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
    assert "../research_pack/2.md" in result


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


@pytest.mark.parametrize("outcome", ["accepted", "rejected", "changed_sources"])
def test_review_controls_export_and_preserves_original_response(
    data, tmp_path, monkeypatch, outcome
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
    if outcome == "changed_sources":
        saved_input = json.loads((evidence / "input.json").read_text())
        saved_input["documents"][0]["sha256"] = "changed"
        (evidence / "input.json").write_text(json.dumps(saved_input))
    monkeypatch.setattr(workflow, "load_documents", lambda *args: (docs, []))
    original = brief.model_dump_json()
    calls = []
    review = review_for(ledger, brief)
    if outcome == "rejected":
        review.fact_checks[0].supported = False
        review.fact_checks[0].reason = "The amount belongs to a different metric."

    def generate(settings, **kwargs):
        calls.append(kwargs)
        output = (
            original
            if kwargs["schema"] == ResearchBrief.model_json_schema()
            else review.model_dump_json()
        )
        return ConnectionReceipt(
            "now",
            "fixture",
            "gemini-3.8-flash",
            "gemini-3.8-flash",
            "test",
            output,
            0.1,
            1,
            100,
            100,
            0,
            200,
        )

    monkeypatch.setattr(workflow, "generate_text", generate)
    exports = tmp_path / "submission"
    kwargs = dict(
        ticker="EXAMPLE",
        company=None,
        docs_dir=tmp_path / "docs",
        as_of=date(2026, 9, 23),
        output_root=tmp_path / "runs",
        writer_version="writer_v5",
        evidence_run=evidence,
        export_dir=exports,
    )
    if outcome == "changed_sources":
        with pytest.raises(workflow.WorkflowFailure, match="checksums"):
            workflow.run_research(GeminiSettings("offline", "test"), **kwargs)
        assert calls == []
        assert not exports.exists()
        return
    if outcome == "rejected":
        with pytest.raises(workflow.WorkflowFailure, match="different metric") as caught:
            workflow.run_research(GeminiSettings("offline", "test"), **kwargs)
        folder = caught.value.run_dir
        assert not (folder / "brief.md").exists()
        assert not (folder / "brief.json").exists()
        assert not exports.exists()
        assert (folder / "response.txt").read_text().strip() == original
        assert (folder / "review_response.txt").exists()
        return
    result = workflow.run_research(GeminiSettings("offline", "test"), **kwargs)
    assert (result.directory / "response.txt").read_text().strip() == original
    assert json.loads((result.directory / "run.json").read_text())["status"] == "complete"
    assert not json.loads((result.directory / "run.json").read_text())["fresh_extraction"]
    assert len(calls) == 2
    assert calls[0]["schema"] == ResearchBrief.model_json_schema()
    assert "C01" in json.loads(calls[0]["prompt"])["conflict_ids"]
    exported = json.loads((exports / "evidence.json").read_text())
    assert exported["ledger"] == ledger.model_dump()
    assert exported["brief"] == brief.model_dump()
    assert exported["model_review"] == review.model_dump()
    assert exported["checks"]["model_review_passed"]
    assert not exported["checks"]["semantic_proof"]
    assert exported["hand_edited"] is False
    assert "../docs/1.md" in (exports / "EXAMPLE_brief.md").read_text()


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


def review_for(ledger, brief):
    return GroundingReview.model_validate(
        {
            "source_checks": [
                {"source_id": item.source_id, "supported": True, "reason": "Correct source role."}
                for item in ledger.source_decisions
            ],
            "conflict_checks": [
                {"conflict_id": f"C{i:02}", "supported": True, "reason": "Keeps both figures."}
                for i, _ in enumerate(ledger.conflicts, 1)
            ],
            "fact_checks": [
                {"fact_id": f.fact_id, "supported": True, "reason": "Matches the quoted source."}
                for f in ledger.facts
            ],
            "brief_checks": [
                {
                    "section": section,
                    "point_index": index,
                    "supported": True,
                    "reason": "Follows from the referenced evidence.",
                }
                for section in ["snapshot", "bull_case", "bear_case", "open_questions"]
                for index, _ in enumerate(getattr(brief, section))
            ],
        }
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_fact",
        "missing_point",
        "duplicate",
        "unsupported",
        "empty_reason",
        "missing_source",
        "missing_conflict",
        "unsupported_conflict",
        "unsupported_source",
    ],
)
def test_review_requires_complete_approved_coverage(data, mutation):
    from research_agent.validation import validate_review

    ledger, brief, _ = data
    review = review_for(ledger, brief)
    if mutation == "missing_fact":
        review.fact_checks = []
    elif mutation == "missing_point":
        review.brief_checks.pop()
    elif mutation == "duplicate":
        review.fact_checks.append(review.fact_checks[0])
    elif mutation == "unsupported":
        review.fact_checks[0].supported = False
        review.fact_checks[0].reason = "The amount belongs to capex, not revenue."
    elif mutation == "missing_source":
        review.source_checks.pop()
    elif mutation == "missing_conflict":
        review.conflict_checks = []
    elif mutation == "unsupported_conflict":
        review.conflict_checks[0].supported = False
        review.conflict_checks[0].reason = "The cause of the discrepancy is unknown."
    elif mutation == "unsupported_source":
        review.source_checks[0].supported = False
        review.source_checks[0].reason = "The company does not match."
    else:
        review.brief_checks[0].reason = ""
    with pytest.raises(ValidationFailure):
        validate_review(review, ledger, brief)


@pytest.mark.parametrize(
    "text",
    ["The company's revenue rose.", "It’s growing.", "Don’t assume growth.", "We can't tell."],
)
def test_brief_rejects_apostrophes(data, text):
    ledger, brief, _ = data
    brief.snapshot[0].text = text
    with pytest.raises(ValidationFailure, match="apostrophes"):
        validate_brief(brief, ledger)


def test_citations_link_to_original_files_with_spaces(data, tmp_path):
    ledger, brief, docs = data
    from dataclasses import replace

    docs = [replace(doc, filename=f"Source {i}.md") for i, doc in enumerate(docs, 1)]
    source_dir = tmp_path / "research pack"
    source_dir.mkdir()
    export_dir = tmp_path / "submission"
    export_dir.mkdir()
    for doc in docs:
        (source_dir / doc.filename).write_text(doc.body)
    result = render_markdown(
        brief, ledger, docs, "EXAMPLE", None, date(2026, 9, 23), "../research pack"
    )
    assert "../research%20pack/Source%201.md" in result
    assert (export_dir / unquote("../research%20pack/Source%201.md")).is_file()
