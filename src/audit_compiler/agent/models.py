"""Investigation-domain models for the interactive audit agent.

These models are the shared contract between the deterministic tool layer, the OpenAI
planner loop, the API, and the frontend. Unlike the immutable evidence models in
``audit_compiler.models``, investigation state is mutable: the loop updates hypotheses and
appends observations as it works. Monetary values are always ``Decimal`` — never float.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InvestigationStatus(StrEnum):
    PLANNING = "planning"
    ACTIVE = "active"
    AWAITING_AUDITOR = "awaiting_auditor"
    SUBMITTED = "submitted"
    DISMISSED = "dismissed"
    STOPPED = "stopped"
    COMPLETED = "completed"


class HypothesisStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    DISMISSED = "dismissed"
    SUBMITTED = "submitted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    AWAITING_AUDITOR = "awaiting_auditor"


class HypothesisCategory(StrEnum):
    VENDOR_INTEGRITY = "vendor_integrity"
    SPLIT_PAYMENT = "split_payment"
    CAPITALISATION = "capitalisation"
    CUTOFF = "cutoff"
    OTHER = "other"


class ActionStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class VerdictRecommendation(StrEnum):
    CONFIRM = "confirm"
    DISMISS = "dismiss"
    HUMAN_REVIEW = "human_review"
    REJECT = "reject"
    UNDECIDED = "undecided"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("monetary values must be Decimal/int/str, never float")
    return value


class ToolCalculationInput(_Model):
    label: str
    value: Decimal
    evidence_id: str

    _no_float = field_validator("value", mode="before")(_reject_float)


class ToolCalculation(_Model):
    """A deterministic calculation produced by a tool; the LLM never fills this in."""

    expression: str
    inputs: tuple[ToolCalculationInput, ...] = ()
    result: Decimal
    sql: str = ""

    _no_float = field_validator("result", mode="before")(_reject_float)


class ToolResult(_Model):
    """What a deterministic agent tool returns. Evidence ids must already exist."""

    tool_name: str
    ok: bool = True
    structured_result: dict = Field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    calculation: ToolCalculation | None = None
    errors: tuple[str, ...] = ()


class PlannedAction(_Model):
    action_id: UUID = Field(default_factory=uuid4)
    tool_name: str
    reason: str
    arguments: dict = Field(default_factory=dict)
    status: ActionStatus = ActionStatus.PLANNED


class ToolObservation(_Model):
    action_id: UUID
    tool_name: str
    structured_result: dict = Field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    calculation: ToolCalculation | None = None
    errors: tuple[str, ...] = ()
    timestamp: datetime


class Hypothesis(_Model):
    hypothesis_id: UUID = Field(default_factory=uuid4)
    claim: str
    category: HypothesisCategory
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    priority: int = Field(default=0, ge=0)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    candidate_exposure: Decimal | None = None
    next_actions: list[str] = Field(default_factory=list)
    verdict_recommendation: VerdictRecommendation = VerdictRecommendation.UNDECIDED

    _no_float = field_validator("candidate_exposure", mode="before")(_reject_float)


class Investigation(_Model):
    investigation_id: UUID = Field(default_factory=uuid4)
    engagement_id: str
    objective: str
    status: InvestigationStatus = InvestigationStatus.PLANNING
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    completed_actions: list[ToolObservation] = Field(default_factory=list)
    pending_actions: list[PlannedAction] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    questions_for_auditor: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    def hypothesis(self, hypothesis_id: UUID | str) -> Hypothesis | None:
        target = str(hypothesis_id)
        return next((h for h in self.hypotheses if str(h.hypothesis_id) == target), None)
