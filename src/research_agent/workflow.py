"""Extract, write, and review research while keeping the original model replies."""

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from importlib.resources import files
from pathlib import Path

from pydantic import ValidationError

from .config import GeminiSettings
from .documents import DocumentError, load_documents
from .evidence import ExtractionFailure, extract_evidence, save_reply, write_json
from .gemini import GeminiRequestError, generate_text
from .models import EvidenceLedger, GroundingReview, ResearchBrief
from .render import render_markdown
from .validation import (
    ValidationFailure,
    validate_brief,
    validate_ledger,
    validate_review,
    word_count,
)

WRITER_PROMPT_VERSION = "writer_v5"
REVIEW_PROMPT_VERSION = "review_v1"


class WorkflowFailure(RuntimeError):
    def __init__(self, message: str, run_dir: Path):
        self.run_dir = run_dir
        super().__init__(message)


@dataclass(frozen=True)
class ResearchRun:
    directory: Path
    brief: ResearchBrief
    ledger: EvidenceLedger


def run_research(
    settings: GeminiSettings,
    *,
    ticker: str,
    company: str | None,
    docs_dir: Path,
    as_of: date,
    output_root: Path,
    writer_version: str = WRITER_PROMPT_VERSION,
    evidence_run: Path | None = None,
    export_dir: Path | None = None,
) -> ResearchRun:
    ticker = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9&._-]{0,29}", ticker):
        raise DocumentError("Use a valid NSE ticker.")
    if output_root.resolve().is_relative_to(docs_dir.resolve()):
        raise DocumentError("Save runs outside the source directory to preserve inputs.")
    if export_dir and export_dir.resolve().is_relative_to(docs_dir.resolve()):
        raise DocumentError("Save exports outside the source directory to preserve inputs.")
    if writer_version != WRITER_PROMPT_VERSION:
        raise DocumentError("Unknown writer prompt version.")
    prompt = files("research_agent").joinpath(f"prompts/{writer_version}.md").read_text()
    docs, future = load_documents(docs_dir, as_of)
    if not docs:
        raise DocumentError("No sources are eligible; no model request was made.")
    started = datetime.now(timezone.utc)
    folder = output_root / f"research-{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True, exist_ok=False)
    run = {
        "status": "running",
        "ticker": ticker.upper(),
        "company": company,
        "as_of": as_of.isoformat(),
        "model": settings.model,
        "started_at_utc": started.isoformat(),
        "writer_version": writer_version,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "fresh_extraction": evidence_run is None,
        "excluded_future_sources": len(future),
        "hand_edited": False,
    }
    write_json(folder / "run.json", run)
    response_prefix = ""
    try:
        if evidence_run is None:
            print("Stage 1/3: reading sources and collecting evidence...", flush=True)
            extracted = extract_evidence(
                settings,
                ticker=ticker,
                company=company,
                docs_dir=docs_dir,
                as_of=as_of,
                output_root=folder / "evidence",
            )
            evidence_run = extracted.directory
        else:
            print("Stage 1/3: checking saved evidence...", flush=True)
        saved_input = json.loads((evidence_run / "input.json").read_text())
        if (
            saved_input["ticker"] != ticker.upper()
            or saved_input["as_of"] != as_of.isoformat()
            or saved_input.get("company") != company
            or {doc["filename"]: doc["sha256"] for doc in saved_input["documents"]}
            != {doc.filename: doc.sha256 for doc in docs}
        ):
            raise DocumentError("Saved evidence does not match target, date, and source checksums.")
        ledger = EvidenceLedger.model_validate_json((evidence_run / "ledger.json").read_text())
        validate_ledger(ledger, docs)
        write_json(folder / "ledger.json", ledger.model_dump())
        run["evidence_directory"] = str(evidence_run.resolve())
        evidence_metadata = json.loads((evidence_run / "run.json").read_text())
        run["evidence_prompt_version"] = evidence_metadata["prompt_version"]
        payload = {
            "ticker": ticker.upper(),
            "company": company,
            "as_of": as_of.isoformat(),
            "ledger": ledger.model_dump(),
            "conflict_ids": {f"C{i:02}": c.model_dump() for i, c in enumerate(ledger.conflicts, 1)},
        }
        write_json(folder / "writer_input.json", payload)
        (folder / "system_prompt.md").write_text(prompt)
        write_json(folder / "schema.json", ResearchBrief.model_json_schema())
        print("Stage 2/3: writing the brief...", flush=True)
        receipt = generate_text(
            settings,
            prompt=json.dumps(payload, ensure_ascii=False),
            system_instruction=prompt,
            schema=ResearchBrief.model_json_schema(),
            thinking_level="medium",
            max_output_tokens=12000,
            timeout_seconds=180,
        )
        save_reply(folder, receipt)
        brief = ResearchBrief.model_validate_json(receipt.response)
        validate_brief(brief, ledger)
        print("Stage 3/3: checking the meaning of each claim...", flush=True)
        review_prompt = (
            files("research_agent").joinpath(f"prompts/{REVIEW_PROMPT_VERSION}.md").read_text()
        )
        review_input = {
            "ticker": ticker.upper(),
            "company": company,
            "as_of": as_of.isoformat(),
            "documents": [doc.as_dict() for doc in docs],
            "ledger": ledger.model_dump(),
            "brief": brief.model_dump(),
        }
        write_json(folder / "review_input.json", review_input)
        (folder / "review_prompt.md").write_text(review_prompt)
        response_prefix = "review_"
        review_receipt = generate_text(
            settings,
            prompt=json.dumps(review_input, ensure_ascii=False),
            system_instruction=review_prompt,
            schema=GroundingReview.model_json_schema(),
            thinking_level="medium",
            max_output_tokens=12000,
            timeout_seconds=180,
        )
        save_reply(folder, review_receipt, response_prefix)
        review = GroundingReview.model_validate_json(review_receipt.response)
        write_json(folder / "review.json", review.model_dump())
        validate_review(review, ledger, brief)
        write_json(folder / "brief.json", brief.model_dump())
        (folder / "brief.md").write_text(
            render_markdown(
                brief,
                ledger,
                docs,
                ticker.upper(),
                company,
                as_of,
                source_base=Path(os.path.relpath(docs_dir, folder)).as_posix(),
            )
        )
        write_json(
            folder / "validation.json",
            {
                "passed": True,
                "word_count": word_count(brief),
                "max_words": 450,
                "source_excerpts_matched": True,
                "references_known": True,
                "numeric_source_checks": True,
                "model_review_passed": True,
                "semantic_entailment_verified": False,
            },
        )
        run["status"] = "complete"
        run["word_count"] = word_count(brief)
        run["review_version"] = REVIEW_PROMPT_VERSION
        if export_dir:
            export_dir.mkdir(parents=True, exist_ok=True)
            markdown = render_markdown(
                brief,
                ledger,
                docs,
                ticker.upper(),
                company,
                as_of,
                source_base=Path(os.path.relpath(docs_dir, export_dir)).as_posix(),
            )
            evidence_data = {
                "ticker": ticker.upper(),
                "company": company,
                "as_of": as_of.isoformat(),
                "model": settings.model,
                "prompts": {
                    "evidence": run["evidence_prompt_version"],
                    "writer": writer_version,
                    "review": REVIEW_PROMPT_VERSION,
                },
                "source_files": [
                    {key: value for key, value in doc.as_dict().items() if key != "body"}
                    for doc in docs
                ],
                "ledger": ledger.model_dump(),
                "brief": brief.model_dump(),
                "model_review": review.model_dump(),
                "checks": {
                    "exact_quotes": True,
                    "numeric_excerpts": True,
                    "model_review_passed": True,
                    "semantic_proof": False,
                },
                "word_count": word_count(brief),
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "brief_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
                "prompt_sha256": {
                    "evidence": evidence_metadata.get("prompt_sha256"),
                    "writer": run["prompt_sha256"],
                    "review": hashlib.sha256(review_prompt.encode()).hexdigest(),
                },
                "extraction_receipts": [
                    json.loads(path.read_text())
                    for path in [
                        evidence_run / "receipt.json",
                        evidence_run / "repair_receipt.json",
                    ]
                    if path.exists()
                ],
                "model_correction_calls": evidence_metadata.get("model_correction_calls", 0),
                "hand_edited": False,
                "writer_response_sha256": hashlib.sha256(receipt.response.encode()).hexdigest(),
                "writer_receipt": {k: v for k, v in asdict(receipt).items() if k != "response"},
                "review_receipt": {
                    k: v for k, v in asdict(review_receipt).items() if k != "response"
                },
            }
            write_json(export_dir / "evidence.json", evidence_data)
            (export_dir / f"{ticker.upper()}_brief.md").write_text(markdown)
            run["exported_to"] = str(export_dir.resolve())
    except (
        ExtractionFailure,
        GeminiRequestError,
        ValidationFailure,
        ValidationError,
        DocumentError,
        OSError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        if isinstance(exc, GeminiRequestError) and exc.receipt:
            save_reply(folder, exc.receipt, response_prefix)
            write_json(folder / "diagnostics.json", exc.diagnostics or {})
        message = (
            "Model JSON failed the requested schema."
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        run["status"] = "failed"
        run["error"] = message
        run["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(folder / "run.json", run)
        write_json(folder / "validation.json", {"passed": False, "error": message})
        raise WorkflowFailure(message, folder) from None
    run["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(folder / "run.json", run)
    return ResearchRun(folder, brief, ledger)
