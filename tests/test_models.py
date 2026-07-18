from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from audit_compiler.models import (
    Case,
    CaseStatus,
    ControlResult,
    ControlStatus,
    EvidenceRef,
    FinancialEvent,
    SourceType,
)


@pytest.fixture
def evidence() -> EvidenceRef:
    return EvidenceRef(
        source_path="ledger/entries.csv",
        source_type=SourceType.CSV_ROW,
        file_sha256="a" * 64,
        raw_value="Example raw source value",
        row=2,
    )


def test_evidence_ref_is_immutable_and_hash_bound(evidence: EvidenceRef) -> None:
    with pytest.raises(ValidationError):
        evidence.raw_value = "changed"
    assert evidence.file_sha256 == "a" * 64
    assert evidence.raw_value_sha256 is not None


def test_financial_event_requires_evidence_and_decimal_money(evidence: EvidenceRef) -> None:
    event = FinancialEvent(
        kind="invoice_posted",
        occurred_on=date(2026, 1, 2),
        net_amount=Decimal("12.34"),
        evidence_refs=(evidence,),
    )
    assert event.net_amount == Decimal("12.34")

    with pytest.raises(ValidationError):
        FinancialEvent(kind="invoice_posted", occurred_on=date.today(), evidence_refs=())
    with pytest.raises(ValidationError):
        FinancialEvent(
            kind="invoice_posted",
            occurred_on=date.today(),
            net_amount=12.34,
            evidence_refs=(evidence,),
        )


def test_control_result_and_case_require_provenance(evidence: EvidenceRef) -> None:
    result = ControlResult(
        rule_id="rule",
        rule_version="1",
        status=ControlStatus.CANDIDATE,
        evidence_refs=(evidence,),
        exposure_amount=Decimal("5"),
        executed_at=datetime.now(UTC),
    )
    case = Case(
        title="Case for review",
        status=CaseStatus.REVIEW_NEEDED,
        control_result_ids=(result.result_id,),
        evidence_refs=(evidence,),
        financial_impact=Decimal("5"),
        created_at=datetime.now(UTC),
    )
    assert case.control_result_ids == (result.result_id,)
