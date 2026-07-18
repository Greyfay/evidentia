"""Immutable, provenance-first Audit Intermediate Representation models."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceType(StrEnum):
    """The native format used to produce an evidence reference."""

    TEXT_ROW = "text_row"
    CSV_ROW = "csv_row"
    XLSX_CELL = "xlsx_cell"
    DOCX_PARAGRAPH = "docx_paragraph"
    PDF_PASSAGE = "pdf_passage"
    XML_NODE = "xml_node"
    FILE = "file"


class CaseStatus(StrEnum):
    CONFIRMED = "confirmed"
    REVIEW_NEEDED = "review_needed"
    DISMISSED = "dismissed"


class ControlStatus(StrEnum):
    CANDIDATE = "candidate"
    CLEARED = "cleared"
    INCONCLUSIVE = "inconclusive"


class DataLocale(StrEnum):
    """The explicit convention used for source amounts and dates."""

    DE = "de"
    EN = "en"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
EvidenceList = Annotated[tuple["EvidenceRef", ...], Field(min_length=1)]


class ImmutableModel(BaseModel):
    """Base model that rejects unknown fields and mutation after construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceRef(ImmutableModel):
    """An exact, hash-bound pointer to a raw value in a supplied source."""

    evidence_id: UUID = Field(default_factory=uuid4)
    source_path: str = Field(min_length=1)
    source_type: SourceType
    file_sha256: Sha256
    raw_value: str
    raw_value_sha256: Sha256
    normalized_value: str | None = None
    extraction_method: str = "native"
    row: int | None = Field(default=None, ge=1)
    sheet: str | None = None
    cell: str | None = None
    page: int | None = Field(default=None, ge=1)
    passage: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_and_validate_raw_value_hash(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "raw_value" not in data:
            return data
        values = dict(data)
        expected = sha256(str(values["raw_value"]).encode("utf-8")).hexdigest()
        supplied = values.get("raw_value_sha256")
        if supplied is not None and supplied != expected:
            raise ValueError("raw_value_sha256 does not match raw_value")
        values["raw_value_sha256"] = expected
        return values

    @field_validator("source_path")
    @classmethod
    def source_path_is_relative(cls, value: str) -> str:
        if value.startswith(("/", "\\")) or ".." in value.split("/"):
            raise ValueError("source_path must be a safe dossier-relative path")
        return value


class EngagementIdentity(ImmutableModel):
    """Stable identity and normalization policy for a compiled dossier."""

    engagement_id: UUID
    name: str = Field(min_length=1)
    dossier_root: str = Field(min_length=1)
    locale: DataLocale


class CompilationRun(ImmutableModel):
    """One isolated attempt to compile an engagement."""

    run_id: UUID = Field(default_factory=uuid4)
    engagement_id: UUID
    status: RunStatus = RunStatus.RUNNING
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    error: str | None = None

    @model_validator(mode="after")
    def completion_matches_status(self) -> CompilationRun:
        if self.status is RunStatus.RUNNING and self.completed_at is not None:
            raise ValueError("a running compilation cannot have completed_at")
        if self.status is not RunStatus.RUNNING and self.completed_at is None:
            raise ValueError("a finished compilation requires completed_at")
        if self.status is RunStatus.FAILED and not self.error:
            raise ValueError("a failed compilation requires an error")
        return self


class FinancialEvent(ImmutableModel):
    """A normalized accounting event that cannot exist without provenance."""

    event_id: UUID = Field(default_factory=uuid4)
    kind: str = Field(min_length=1)
    occurred_on: date
    party_ids: tuple[str, ...] = ()
    account_ids: tuple[str, ...] = ()
    user_id: str | None = None
    document_id: str | None = None
    net_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    gross_amount: Decimal | None = None
    evidence_refs: EvidenceList

    @field_validator("net_amount", "tax_amount", "gross_amount", mode="before")
    @classmethod
    def reject_float_money(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("money must be supplied as Decimal, integer, or string; never float")
        return value


class ControlResult(ImmutableModel):
    """A replayable outcome from deterministic control execution."""

    result_id: UUID = Field(default_factory=uuid4)
    rule_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    status: ControlStatus
    event_ids: tuple[UUID, ...] = ()
    evidence_refs: EvidenceList
    exposure_amount: Decimal | None = None
    calculation_steps: tuple[str, ...] = ()
    parameters: tuple[tuple[str, str], ...] = ()
    executed_at: datetime

    @field_validator("exposure_amount", mode="before")
    @classmethod
    def reject_float_exposure(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("money must be supplied as Decimal, integer, or string; never float")
        return value


class Case(ImmutableModel):
    """A reviewer-facing case with evidence, results, and an explicit disposition."""

    case_id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1)
    status: CaseStatus
    control_result_ids: tuple[UUID, ...]
    evidence_refs: EvidenceList
    financial_event_ids: tuple[UUID, ...] = ()
    financial_impact: Decimal | None = None
    uncertainty: str | None = None
    review_note: str | None = None
    created_at: datetime

    @field_validator("financial_impact", mode="before")
    @classmethod
    def reject_float_impact(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("money must be supplied as Decimal, integer, or string; never float")
        return value
