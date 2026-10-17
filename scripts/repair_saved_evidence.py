"""Resume an interrupted evidence stage using the same deterministic quote policy."""

import json
import sys
from datetime import date
from pathlib import Path

from research_agent.documents import load_documents
from research_agent.evidence import align_quotations, render_evidence, write_json
from research_agent.models import EvidenceLedger
from research_agent.validation import validate_ledger

folder = Path(sys.argv[1]).resolve()
payload = json.loads((folder / "input.json").read_text())
docs, _ = load_documents(Path("research_pack"), date.fromisoformat(payload["as_of"]))
assert {doc.filename: doc.sha256 for doc in docs} == {
    doc["filename"]: doc["sha256"] for doc in payload["documents"]
}
ledger = EvidenceLedger.model_validate_json((folder / "response.txt").read_text())
changes = align_quotations(ledger, docs)
validate_ledger(ledger, docs)
for name in ("run.json", "validation.json"):
    original = folder / ("initial_" + name)
    if not original.exists():
        original.write_bytes((folder / name).read_bytes())
write_json(folder / "quote_alignment.json", {"automatic": True, "changes": changes})
write_json(folder / "ledger.json", ledger.model_dump())
(folder / "review.md").write_text(
    render_evidence(ledger, docs, payload["ticker"], date.fromisoformat(payload["as_of"]))
)
run = json.loads((folder / "run.json").read_text())
run.update(status="validated", resumed_after_quote_alignment=True)
write_json(folder / "run.json", run)
write_json(
    folder / "validation.json",
    {
        "passed": True,
        "automatic_quote_alignments": len(changes),
        "semantic_entailment_verified": False,
    },
)
print(f"Revalidated {folder}; {len(changes)} automatic quote alignments; no model call.")
