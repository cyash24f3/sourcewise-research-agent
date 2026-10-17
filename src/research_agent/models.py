"""Schemas sent to the API and checked again locally."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceDecision(StrictModel):
    source_id: str
    disposition: Literal["use", "context_only", "exclude"]
    reason: str


class EvidenceQuote(StrictModel):
    source_id: str
    quote: str = Field(
        description="Copy an exact passage from the source body, including Markdown."
    )


class Fact(StrictModel):
    fact_id: str
    claim: str
    kind: Literal["reported", "management_expectation", "inference"]
    evidence: list[EvidenceQuote]


class Conflict(StrictModel):
    topic: str
    source_ids: list[str]
    resolution: str
    evidence: list[EvidenceQuote]


class EvidenceLedger(StrictModel):
    source_decisions: list[SourceDecision]
    facts: list[Fact]
    conflicts: list[Conflict]


class BriefPoint(StrictModel):
    text: str
    fact_ids: list[str]
    conflict_ids: list[str] = Field(default_factory=list)


class ResearchBrief(StrictModel):
    snapshot: list[BriefPoint]
    bull_case: list[BriefPoint]
    bear_case: list[BriefPoint]
    open_questions: list[BriefPoint]

    def sections(self) -> list[tuple[str, list[BriefPoint]]]:
        return [
            ("Snapshot", self.snapshot),
            ("Bull case", self.bull_case),
            ("Bear case", self.bear_case),
            ("Open questions", self.open_questions),
        ]


class FactCheck(StrictModel):
    fact_id: str
    supported: bool
    reason: str


class BriefCheck(StrictModel):
    section: Literal["snapshot", "bull_case", "bear_case", "open_questions"]
    point_index: int = Field(ge=0)
    supported: bool
    reason: str


class SourceCheck(StrictModel):
    source_id: str
    supported: bool
    reason: str


class ConflictCheck(StrictModel):
    conflict_id: str
    supported: bool
    reason: str


class GroundingReview(StrictModel):
    source_checks: list[SourceCheck]
    conflict_checks: list[ConflictCheck]
    fact_checks: list[FactCheck]
    brief_checks: list[BriefCheck]
