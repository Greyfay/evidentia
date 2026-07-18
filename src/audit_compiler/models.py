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


class CounterTestOutcome(StrEnum):
    """Canonical result of looking for evidence that could refute a finding."""

    PRESENT = "present"
    SEARCHED_ABSENT = "searched_absent"
    UNKNOWN = "unknown"
    NOT_EXECUTED = "not_executed"
    NOT_APPLICABLE = "not_applicable"
    CONFLICTING = "conflicting"


class CounterEvidenceSearch(ImmutableModel):
    """Replayable description of a counter-evidence search.

    Sources and evidence identifiers are sorted because they are sets in the audit
    domain.  This prevents discovery order from changing a contract hash.
    """

    scope: str = Field(min_length=1)
    method: str = Field(min_length=1)
    searched_sources: tuple[str, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()

    @field_validator("searched_sources")
    @classmethod
    def canonical_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not source for source in value):
            raise ValueError("searched_sources cannot contain empty values")
        return tuple(sorted(set(value)))

    @field_validator("evidence_ids")
    @classmethod
    def canonical_evidence_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(sorted(set(value), key=str))


# Kept as a public alias for callers which used the pre-enum annotation.
CounterOutcome = CounterTestOutcome


class CounterTest(ImmutableModel):
    name: str = Field(min_length=1)
    outcome: CounterTestOutcome
    detail: str
    required: bool = True
    evidence: tuple[EvidenceRef, ...] = ()
    search: CounterEvidenceSearch | None = None

    @model_validator(mode="before")
    @classmethod
    def parse_legacy_absence_conservatively(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("outcome") == "absent":
            values = dict(data)
            values["outcome"] = CounterTestOutcome.UNKNOWN
            return values
        return data

    @model_validator(mode="after")
    def validate_search_claim(self) -> CounterTest:
        if self.outcome == CounterTestOutcome.SEARCHED_ABSENT and self.search is None:
            raise ValueError("searched_absent requires counter-evidence search metadata")
        return self


class AdmissionSignals(ImmutableModel):
    """Facts consumed by admission, without embedding admission policy."""

    conflicting_evidence: bool = False
    material_uncertainty: bool = False
    accounting_judgement: bool = False
    incomplete_supporting_evidence: bool = False


class ReplayInput(ImmutableModel):
    name: str = Field(min_length=1)
    value: str


class ReplayBinding(ImmutableModel):
    name: str = Field(min_length=1)
    evidence_id: UUID


class ReplaySpecification(ImmutableModel):
    """Complete identity and inputs required to reproduce a deterministic run."""

    engagement_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    control_id: str = Field(min_length=1)
    control_version: str = Field(min_length=1)
    runtime_version: str = Field(min_length=1)
    inputs: tuple[ReplayInput, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    bindings: tuple[ReplayBinding, ...] = ()

    @field_validator("evidence_ids")
    @classmethod
    def canonical_replay_evidence(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(sorted(set(value), key=str))

    @field_validator("inputs")
    @classmethod
    def canonical_inputs(cls, value: tuple[ReplayInput, ...]) -> tuple[ReplayInput, ...]:
        return tuple(sorted(value, key=lambda item: (item.name, item.value)))

    @field_validator("bindings")
    @classmethod
    def canonical_bindings(
        cls, value: tuple[ReplayBinding, ...]
    ) -> tuple[ReplayBinding, ...]:
        return tuple(sorted(value, key=lambda item: (item.name, str(item.evidence_id))))


class AdmissionReasonCode(StrEnum):
    """Stable reason identifiers; display text is deliberately not policy input."""

    EVIDENCE_AND_CONTROLS_SUPPORT = "evidence_and_controls_support"
    COUNTER_EVIDENCE_PRESENT = "counter_evidence_present"
    COUNTER_EVIDENCE_CONFLICTING = "counter_evidence_conflicting"
    COUNTER_TEST_INCOMPLETE = "counter_test_incomplete"
    MATERIAL_UNCERTAINTY = "material_uncertainty"
    ACCOUNTING_JUDGEMENT = "accounting_judgement"
    SUPPORTING_EVIDENCE_INCOMPLETE = "supporting_evidence_incomplete"
    EVIDENCE_CHAIN_MISSING = "evidence_chain_missing"
    CALCULATION_SUPPORT_MISSING = "calculation_support_missing"
    CONTROL_SUPPORT_MISSING = "control_support_missing"


class AdmissionReason(ImmutableModel):
    """Machine-readable admission explanation with optional human-facing detail."""

    code: AdmissionReasonCode
    detail: str | None = None
    evidence_ids: tuple[UUID, ...] = ()

    @field_validator("evidence_ids")
    @classmethod
    def canonical_reason_evidence(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(sorted(set(value), key=str))


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
    admission_signals: AdmissionSignals = Field(default_factory=AdmissionSignals)
    replay: ReplaySpecification | None = None

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
    admission_reasons: tuple[AdmissionReason, ...] = ()
    replay: ReplaySpecification | None = None
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
