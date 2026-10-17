"""Assess sources and extract an auditable, locally validated evidence ledger."""

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from importlib.resources import files
from pathlib import Path

from pydantic import ValidationError

from .config import GeminiSettings
from .documents import DocumentError, build_manifest, load_documents
from .gemini import ConnectionReceipt, GeminiRequestError, generate_text
from .models import EvidenceLedger
from .render import plain
from .validation import ValidationFailure, normalize, validate_ledger

EVIDENCE_PROMPT_VERSION = "evidence_v4"


class ExtractionFailure(RuntimeError):
    def __init__(self, message: str, run_dir: Path):
        self.run_dir = run_dir
        super().__init__(message)


@dataclass(frozen=True)
class EvidenceRun:
    directory: Path
    ledger: EvidenceLedger
    receipt: ConnectionReceipt


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def align_quotations(ledger: EvidenceLedger, docs: list) -> list[dict]:
    """Recover near-verbatim long quotes from one unambiguous source paragraph.

    Only excerpts change, never claims or IDs. All changes retain before/after text;
    the usual exact-quote and numeric checks still run after alignment.
    """
    sources = {doc.source_id: doc for doc in docs}
    excluded = {d.source_id for d in ledger.source_decisions if d.disposition == "exclude"}
    changes = []
    entries = [(fact.fact_id, fact.evidence) for fact in ledger.facts]
    entries += [(f"C{i:02}", c.evidence) for i, c in enumerate(ledger.conflicts, 1)]
    for label, quotes in entries:
        for index, item in enumerate(quotes):
            if item.source_id not in sources or item.source_id in excluded:
                continue
            body = sources[item.source_id].body
            quote = normalize(item.quote)
            if quote in normalize(body) or len(quote) < 80:
                continue
            candidates = []
            for paragraph in re.split(r"\n\s*\n", body):
                candidate = normalize(paragraph)
                matcher = SequenceMatcher(None, quote, candidate, autojunk=False)
                coverage = sum(block.size for block in matcher.get_matching_blocks()) / len(quote)
                if coverage >= 0.94 and len(candidate) <= len(quote) * 3:
                    candidates.append((coverage, paragraph))
            if len(candidates) == 1:
                before = item.quote
                item.quote = candidates[0][1]
                changes.append(
                    {
                        "location": label,
                        "quote_index": index,
                        "source_id": item.source_id,
                        "original_quote": before,
                        "source_paragraph": item.quote,
                        "coverage": candidates[0][0],
                    }
                )
    return changes


def render_evidence(ledger, docs, ticker: str, as_of: date) -> str:
    sources = {doc.source_id: doc for doc in docs}
    lines = [f"# {plain(ticker)} — evidence review", "", f"As of {as_of.isoformat()}", ""]
    lines += [
        "Exact source excerpts have passed local checks. Source decisions and claim meaning",
        "are model judgements; quote matching does not prove that every inference is correct.",
        "",
        "## Source decisions",
        "",
    ]
    for decision in ledger.source_decisions:
        doc = sources[decision.source_id]
        lines += [
            f"### {decision.source_id}: {plain(doc.filename)} — {decision.disposition}",
            "",
            f"[{plain(doc.source)}](<{doc.url}>) · {doc.published}",
            "",
            plain(decision.reason),
            "",
        ]
    lines += ["## Facts", ""]
    for fact in ledger.facts:
        lines += [f"### {fact.fact_id} · {fact.kind}", "", plain(fact.claim), ""]
        for evidence in fact.evidence:
            doc = sources[evidence.source_id]
            lines += [
                f"[{evidence.source_id}](<{doc.url}>) · `{doc.filename}`",
                "",
                f"> {plain(evidence.quote)}",
                "",
            ]
    lines += ["## Conflicts and temporal updates", ""]
    if not ledger.conflicts:
        lines += ["No material conflicts were identified by the model.", ""]
    for conflict in ledger.conflicts:
        lines += [f"### {plain(conflict.topic)}", "", plain(conflict.resolution), ""]
        for evidence in conflict.evidence:
            doc = sources[evidence.source_id]
            lines += [f"[{evidence.source_id}](<{doc.url}>)", "", f"> {plain(evidence.quote)}", ""]
    return "\n".join(lines)


def extract_evidence(
    settings: GeminiSettings,
    *,
    ticker: str,
    company: str | None,
    docs_dir: Path,
    as_of: date,
    output_root: Path,
    client_factory=None,
) -> EvidenceRun:
    ticker = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9&._-]{0,29}", ticker):
        raise DocumentError(
            "Use a ticker containing letters, digits, &, period, underscore, or hyphen."
        )
    if output_root.resolve().is_relative_to(docs_dir.resolve()):
        raise DocumentError("Save evidence runs outside the source directory to preserve inputs.")
    docs, future = load_documents(docs_dir, as_of)
    if not docs:
        raise DocumentError(
            "No sources are eligible on the research date; no model request was made."
        )
    prompt = (
        files("research_agent")
        .joinpath(f"prompts/{EVIDENCE_PROMPT_VERSION}.md")
        .read_text(encoding="utf-8")
    )
    payload = {
        "ticker": ticker,
        "company": company,
        "as_of": as_of.isoformat(),
        "documents": [doc.as_dict() for doc in docs],
    }
    started = datetime.now(timezone.utc)
    folder = output_root / f"{ticker}-{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / "input.json", payload)
    write_json(folder / "manifest.json", build_manifest(docs, future, as_of))
    (folder / "system_prompt.md").write_text(prompt, encoding="utf-8")
    schema = EvidenceLedger.model_json_schema()
    write_json(folder / "schema.json", schema)
    run = {
        "status": "running",
        "stage": "evidence_extraction",
        "ticker": ticker,
        "company": company,
        "as_of": as_of.isoformat(),
        "model": settings.model,
        "started_at_utc": started.isoformat(),
        "prompt_version": EVIDENCE_PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "thinking_level": "medium",
        "max_output_tokens": 20000,
        "timeout_seconds": 180,
        "eligible_sources": len(docs),
        "excluded_future_sources": len(future),
    }
    write_json(folder / "run.json", run)
    try:
        receipt = generate_text(
            settings,
            prompt=json.dumps(payload, ensure_ascii=False),
            system_instruction=prompt,
            schema=schema,
            client_factory=client_factory,
            thinking_level="medium",
            max_output_tokens=20000,
            timeout_seconds=180,
        )
        (folder / "response.txt").write_text(receipt.response + "\n", encoding="utf-8")
        metadata = asdict(receipt)
        metadata.pop("response")
        write_json(folder / "receipt.json", metadata)
        ledger = EvidenceLedger.model_validate_json(receipt.response)
        alignments = align_quotations(ledger, docs)
        if alignments:
            write_json(folder / "quote_alignment.json", {"automatic": True, "changes": alignments})
        validate_ledger(ledger, docs)
    except (GeminiRequestError, ValidationError, ValidationFailure) as exc:
        if isinstance(exc, GeminiRequestError) and exc.receipt is not None:
            (folder / "response.txt").write_text(exc.receipt.response + "\n", encoding="utf-8")
            metadata = asdict(exc.receipt)
            metadata.pop("response")
            write_json(folder / "receipt.json", metadata)
            write_json(folder / "diagnostics.json", exc.diagnostics or {})
        if isinstance(exc, ValidationError):
            errors = ["Model JSON failed the evidence schema."]
        elif isinstance(exc, ValidationFailure):
            errors = exc.errors
        else:
            errors = [str(exc)]
        run["status"] = "failed"
        run["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(folder / "validation.json", {"passed": False, "errors": errors})
        write_json(folder / "run.json", run)
        raise ExtractionFailure(
            "Evidence extraction failed: " + "; ".join(errors), folder
        ) from None
    write_json(folder / "ledger.json", ledger.model_dump())
    (folder / "review.md").write_text(
        render_evidence(ledger, docs, ticker, as_of), encoding="utf-8"
    )
    write_json(
        folder / "validation.json",
        {
            "passed": True,
            "schema_valid": True,
            "exact_quotes_verified": True,
            "numeric_source_checks": True,
            "source_decisions_complete": True,
            "semantic_entailment_verified": False,
            "fact_count": len(ledger.facts),
            "conflict_count": len(ledger.conflicts),
        },
    )
    run["status"] = "validated"
    run["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(folder / "run.json", run)
    return EvidenceRun(folder, ledger, receipt)
