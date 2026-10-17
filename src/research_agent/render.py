"""Render citations from verified IDs and original metadata, never model-written URLs."""

import re
from datetime import date

from .documents import Document
from .models import EvidenceLedger, ResearchBrief


def plain(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>#|])", r"\\\1", " ".join(text.split()))


def render_markdown(
    brief: ResearchBrief,
    ledger: EvidenceLedger,
    docs: list[Document],
    ticker: str,
    company: str | None,
    as_of: date,
) -> str:
    facts = {fact.fact_id: fact for fact in ledger.facts}
    sources = {doc.source_id: doc for doc in docs}
    conflicts = {f"C{i:02}": item for i, item in enumerate(ledger.conflicts, 1)}
    used = set()
    title = f"{company} ({ticker})" if company else ticker
    lines = [f"# {plain(title)} — research brief", "", f"As of {as_of.isoformat()}", ""]
    for section, points in brief.sections():
        lines += [f"## {section}", ""]
        for point in points:
            ids = sorted(
                {q.source_id for fid in point.fact_ids for q in facts[fid].evidence}
                | {sid for cid in point.conflict_ids for sid in conflicts[cid].source_ids}
            )
            used.update(ids)
            citations = " ".join(f"[{sid}](#source-{sid.lower()})" for sid in ids)
            prefix = "" if section == "Snapshot" else "- "
            lines += [f"{prefix}{plain(point.text)} {citations}"]
        lines.append("")
    lines += ["## Sources", ""]
    for sid in sorted(used):
        doc = sources[sid]
        lines += [
            f'<a id="source-{sid.lower()}"></a>',
            f"- **{sid}** — [{plain(doc.filename)}](<{doc.url}>) · {doc.published}.",
        ]
    lines += ["", "Research based only on the supplied documents.", ""]
    return "\n".join(lines)
