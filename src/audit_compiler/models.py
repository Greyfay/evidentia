"""Immutable, provenance-first Audit Intermediate Representation models."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

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
    """Explicit amount and date convention for an engagement."""

    DE = "de"
    EN = "en"


Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
EvidenceList = Annotated[tuple["EvidenceRef", ...], Field(min_length=1)]


class ImmutableModel(BaseModel):
    """Base model that rejects unknown fields and mutation after construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def deterministic_json(self) -> str:
        """Return a byte-stable JSON representation for hashing and replay."""

        return json.dumps(
            self.model_dump(mode="json", exclude_none=False),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


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

    @classmethod
    def canonical(cls, **values: Any) -> EvidenceRef:
        """Build a content-addressed reference with a deterministic UUID."""

        locator = "|".join(
            str(values.get(key) or "")
            for key in ("source_path", "row", "sheet", "cell", "page", "passage")
        )
        raw_hash = sha256(str(values.get("raw_value", "")).encode("utf-8")).hexdigest()
        values["evidence_id"] = uuid5(NAMESPACE_URL, f"evidentia/evidence/{locator}|{raw_hash}")
        return cls(**values)


class FinancialEvent(ImmutableModel):
    """A normalized accounting event that cannot exist without provenance."""

    event_id: UUID = Field(default_factory=uuid4)
    engagement_id: str = "legacy"
    run_id: str = "legacy"
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


class CanonicalPayment(ImmutableModel):
    """One exact, provenance-bearing payment in the canonical Audit IR."""

    payment_id: str = Field(min_length=1)
    engagement_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    vendor_id: str = Field(min_length=1)
    payment_date: date
    amount: Decimal
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    invoice_id: str | None = None
    approved_by: str | None = None
    reversal_of: str | None = None
    evidence_refs: EvidenceList

    @field_validator("amount", mode="before")
    @classmethod
    def reject_float_amount(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("money must never be supplied as float")
        return value


CounterOutcome = Literal["absent", "present", "not_applicable"]


class CounterTest(ImmutableModel):
    name: str = Field(min_length=1)
    outcome: CounterOutcome
    detail: str
    required: bool = True
    evidence: tuple[EvidenceRef, ...] = ()


class CalculationInput(ImmutableModel):
    label: str
    value: Decimal
    evidence_id: UUID

    @field_validator("value", mode="before")
    @classmethod
    def reject_float_value(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("money must never be supplied as float")
        return value


class CanonicalCalculation(ImmutableModel):
    expression: str
    inputs: tuple[CalculationInput, ...]
    result: Decimal
    sql: str


class ControlOutcome(ImmutableModel):
    """Candidate output. Deliberately has no final-verdict field."""

    outcome_id: UUID
    engagement_id: str
    run_id: str
    control_id: str
    control_version: str
    status: Literal["candidate", "cleared", "inconclusive"]
    subject: str
    event_ids: tuple[UUID, ...] = ()
    exposure_amount: Decimal
    calculation: CanonicalCalculation
    evidence_refs: EvidenceList
    counter_tests: tuple[CounterTest, ...]
    uncertainty: str | None = None

    @field_validator("exposure_amount", mode="before")
    @classmethod
    def reject_float_exposure_amount(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("money must never be supplied as float")
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
    """Admission-owned final case contract.

    The legacy ``status``/``control_result_ids`` fields remain optional during migration.
    New production code uses ``verdict`` and the engagement/run boundary.
    """

    case_id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1)
    engagement_id: str = "legacy"
    run_id: str = "legacy"
    control_id: str = "legacy"
    control_version: str = "legacy"
    verdict: Literal["CONFIRMED", "HUMAN_REVIEW", "DISMISSED", "REJECTED"] | None = None
    status: CaseStatus | None = None
    control_result_ids: tuple[UUID, ...] = ()
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


class SourceCompilation(ImmutableModel):
    path: str
    type: str
    bytes: int = Field(ge=0)
    sha256: Sha256
    status: str
    source_rows: int = Field(ge=0)
    parsed_rows: int = Field(ge=0)
    warnings: tuple[str, ...] = ()


class EngagementSummary(ImmutableModel):
    engagement_id: str
    run_id: str
    name: str
    dossier_root: str
    locale: DataLocale
    compiled_at: datetime
    methodology_version: str
    counts: dict[str, int]
    source_files: tuple[SourceCompilation, ...]


class CaseBundle(ImmutableModel):
    """Deterministically serializable output of the canonical compiler service."""

    schema_version: str = "2.0"
    engagement: EngagementSummary
    cases: tuple[dict[str, Any], ...]
