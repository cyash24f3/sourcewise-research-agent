"""Two-stage, document-grounded research with preserved model output and receipts."""

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from importlib.resources import files
from pathlib import Path

from pydantic import ValidationError

from .config import GeminiSettings
from .documents import DocumentError, load_documents
from .evidence import ExtractionFailure, extract_evidence, write_json
from .gemini import GeminiRequestError, generate_text
from .models import EvidenceLedger, ResearchBrief
from .render import render_markdown
from .validation import ValidationFailure, validate_brief, validate_ledger, word_count


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
    writer_version: str = "writer_v4",
    evidence_run: Path | None = None,
) -> ResearchRun:
    if output_root.resolve().is_relative_to(docs_dir.resolve()):
        raise DocumentError("Save runs outside the source directory to preserve inputs.")
    if writer_version not in {"writer_v1", "writer_v2", "writer_v3", "writer_v4"}:
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
    try:
        if evidence_run is None:
            print("Stage 1/2: assessing sources and extracting evidence...", flush=True)
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
            print("Stage 1/2: revalidating saved evidence (no extraction API call)...", flush=True)
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
        run["evidence_prompt_version"] = json.loads((evidence_run / "run.json").read_text())[
            "prompt_version"
        ]
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
        print("Stage 2/2: writing the cited research brief...", flush=True)
        receipt = generate_text(
            settings,
            prompt=json.dumps(payload, ensure_ascii=False),
            system_instruction=prompt,
            schema=ResearchBrief.model_json_schema(),
            thinking_level="medium",
            max_output_tokens=12000,
            timeout_seconds=180,
        )
        (folder / "response.txt").write_text(receipt.response + "\n")
        metadata = asdict(receipt)
        metadata.pop("response")
        write_json(folder / "receipt.json", metadata)
        brief = ResearchBrief.model_validate_json(receipt.response)
        validate_brief(brief, ledger)
        write_json(folder / "brief.json", brief.model_dump())
        (folder / "brief.md").write_text(
            render_markdown(brief, ledger, docs, ticker.upper(), company, as_of)
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
                "semantic_entailment_verified": False,
            },
        )
        run["status"] = "complete"
        run["word_count"] = word_count(brief)
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
            (folder / "response.txt").write_text(exc.receipt.response + "\n")
            metadata = asdict(exc.receipt)
            metadata.pop("response")
            write_json(folder / "receipt.json", metadata)
            write_json(folder / "diagnostics.json", exc.diagnostics or {})
        message = (
            "Model JSON failed the brief schema." if isinstance(exc, ValidationError) else str(exc)
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
