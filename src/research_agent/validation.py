"""Structural and provenance checks. These do not prove semantic entailment."""

import re
from decimal import Decimal

from .documents import Document
from .models import EvidenceLedger, ResearchBrief


class ValidationFailure(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def normalize(text: str) -> str:
    return " ".join(text.split())


def numeric_values(text: str) -> set[Decimal]:
    # Calendar-year interpretation is semantic, not a quantity-support check.
    # Preserve financial quantities such as ₹2,025 while ignoring "June 2025".
    text = re.sub(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+\d{4}\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return {
        Decimal(value.replace(",", ""))
        for value in re.findall(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?(?!\w|\.\d)", text)
    }


def word_count(brief: ResearchBrief) -> int:
    return sum(len(point.text.split()) for _, points in brief.sections() for point in points)


def validate_ledger(ledger: EvidenceLedger, docs: list[Document]) -> None:
    errors = []
    sources = {doc.source_id: doc for doc in docs}
    decision_ids = [decision.source_id for decision in ledger.source_decisions]
    if len(set(decision_ids)) != len(decision_ids):
        errors.append("Each source needs exactly one decision; duplicate source decisions found.")
    if set(decision_ids) != set(sources):
        errors.append("Source decisions must cover every eligible source exactly once.")
    excluded = {d.source_id for d in ledger.source_decisions if d.disposition == "exclude"}
    for decision in ledger.source_decisions:
        if not decision.reason.strip():
            errors.append(f"{decision.source_id}: missing source decision reason.")
    fact_ids = [fact.fact_id for fact in ledger.facts]
    if not fact_ids:
        errors.append("No supported facts extracted.")
    if len(set(fact_ids)) != len(fact_ids):
        errors.append("Duplicate fact IDs.")

    def check_quotes(label: str, quotes) -> None:
        for evidence in quotes:
            doc = sources.get(evidence.source_id)
            if doc is None:
                errors.append(f"{label}: unknown source {evidence.source_id}.")
            elif evidence.source_id in excluded:
                errors.append(f"{label}: cites excluded source {evidence.source_id}.")
            elif len(normalize(evidence.quote)) < 12:
                errors.append(f"{label}: evidence quote is too short to inspect.")
            elif normalize(evidence.quote) not in normalize(doc.body):
                errors.append(f"{label}: quote not found verbatim in {evidence.source_id}.")

    for fact in ledger.facts:
        if not re.fullmatch(r"F[0-9]{1,4}", fact.fact_id):
            errors.append(f"Invalid fact ID: {fact.fact_id!r}.")
        if not fact.claim.strip() or not fact.evidence:
            errors.append(f"{fact.fact_id}: a claim and source evidence are required.")
        check_quotes(fact.fact_id, fact.evidence)
        if fact.kind != "inference":
            cited = {item.source_id for item in fact.evidence if item.source_id in sources}
            source_text = " ".join(
                sources[sid].body + " " + sources[sid].published for sid in cited
            )
            unsupported = numeric_values(fact.claim) - numeric_values(source_text)
            if unsupported:
                errors.append(
                    f"{fact.fact_id}: numeric claims absent from cited sources: "
                    + ", ".join(str(value) for value in sorted(unsupported))
                    + ". Cite every source needed for the complete claim."
                )
    for conflict in ledger.conflicts:
        if len(set(conflict.source_ids)) < 2 or not set(conflict.source_ids) <= set(sources):
            errors.append("A conflict must reference at least two known, distinct sources.")
        if not conflict.topic.strip() or not conflict.resolution.strip():
            errors.append("A conflict needs a topic and an explicit resolution or uncertainty.")
        if {quote.source_id for quote in conflict.evidence} != set(conflict.source_ids):
            errors.append("A conflict needs at least one exact excerpt from every listed source.")
        check_quotes("Conflict", conflict.evidence)
    if errors:
        raise ValidationFailure(errors)


def validate_brief(brief: ResearchBrief, ledger: EvidenceLedger, max_words: int = 450) -> None:
    errors = []
    facts = {fact.fact_id: fact for fact in ledger.facts}
    conflicts = {f"C{i:02}": conflict for i, conflict in enumerate(ledger.conflicts, 1)}
    for section, points in brief.sections():
        if not points or len(points) > 4:
            errors.append(f"{section}: use 1–4 concise points.")
        for point in points:
            if not point.text.strip():
                errors.append(f"{section}: empty point.")
            if "\n" in point.text or re.search(r"https?://|\]\(|<[^>]+>", point.text):
                errors.append(f"{section}: use plain text; citations are inserted by the renderer.")
            if not point.fact_ids and not point.conflict_ids:
                errors.append(f"{section}: every point needs evidence references.")
            if not set(point.fact_ids) <= set(facts):
                errors.append(f"{section}: unknown fact IDs.")
            if not set(point.conflict_ids) <= set(conflicts):
                errors.append(f"{section}: unknown conflict IDs.")
            support = " ".join(facts[fid].claim for fid in point.fact_ids if fid in facts)
            support += " " + " ".join(
                conflicts[cid].resolution for cid in point.conflict_ids if cid in conflicts
            )
            if numeric_values(point.text) - numeric_values(support):
                errors.append(f"{section}: numeric claim absent from referenced evidence.")
    count = word_count(brief)
    if count > max_words:
        errors.append(f"Brief is {count} words; maximum is {max_words} excluding Sources.")
    if errors:
        raise ValidationFailure(errors)
