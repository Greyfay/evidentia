"""Tests for investigation domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from audit_compiler.agent.models import (
    ActionStatus,
    Hypothesis,
    HypothesisCategory,
    HypothesisStatus,
    Investigation,
    InvestigationStatus,
    PlannedAction,
    ToolCalculation,
    ToolCalculationInput,
    ToolObservation,
    ToolResult,
    VerdictRecommendation,
)


class TestEnumMembers:
    """Verify all enum members are present and expected."""

    def test_investigation_status_members(self):
        expected = {
            "planning", "active", "awaiting_auditor", "submitted", "dismissed", "stopped",
            "completed",
        }
        assert {e.value for e in InvestigationStatus} == expected

    def test_hypothesis_status_members(self):
        expected = {
            "proposed", "active", "supported", "refuted", "dismissed", "submitted",
            "insufficient_evidence", "awaiting_auditor",
        }
        assert {e.value for e in HypothesisStatus} == expected

    def test_hypothesis_category_members(self):
        expected = {"vendor_integrity", "split_payment", "capitalisation", "cutoff", "other"}
        assert {e.value for e in HypothesisCategory} == expected

    def test_action_status_members(self):
        expected = {"planned", "running", "completed", "failed", "skipped"}
        assert {e.value for e in ActionStatus} == expected

    def test_verdict_recommendation_members(self):
        expected = {"confirm", "dismiss", "human_review", "reject", "undecided"}
        assert {e.value for e in VerdictRecommendation} == expected


class TestExtraFieldsForbidden:
    """Verify that models reject extra fields."""

    def test_hypothesis_forbids_extra_fields(self):
        with pytest.raises(ValidationError) as exc_info:
            Hypothesis(
                claim="test",
                category=HypothesisCategory.VENDOR_INTEGRITY,
                unknown_field="value",  # type: ignore
            )
        assert "extra_forbidden" in str(exc_info.value).lower()

    def test_investigation_forbids_extra_fields(self):
        with pytest.raises(ValidationError) as exc_info:
            Investigation(
                engagement_id="test",
                objective="test",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                unknown_field="value",  # type: ignore
            )
        assert "extra_forbidden" in str(exc_info.value).lower()

    def test_tool_observation_forbids_extra_fields(self):
        with pytest.raises(ValidationError) as exc_info:
            ToolObservation(
                action_id=uuid4(),
                tool_name="test",
                timestamp=datetime.now(UTC),
                unknown_field="value",  # type: ignore
            )
        assert "extra_forbidden" in str(exc_info.value).lower()

    def test_planned_action_forbids_extra_fields(self):
        with pytest.raises(ValidationError) as exc_info:
            PlannedAction(
                tool_name="test",
                reason="test",
                unknown_field="value",  # type: ignore
            )
        assert "extra_forbidden" in str(exc_info.value).lower()

    def test_tool_result_forbids_extra_fields(self):
        with pytest.raises(ValidationError) as exc_info:
            ToolResult(
                tool_name="test",
                unknown_field="value",  # type: ignore
            )
        assert "extra_forbidden" in str(exc_info.value).lower()


class TestMonetaryFieldRejectFloat:
    """Verify that monetary fields reject float values."""

    def test_hypothesis_candidate_exposure_rejects_float(self):
        with pytest.raises(ValidationError) as exc_info:
            Hypothesis(
                claim="test",
                category=HypothesisCategory.VENDOR_INTEGRITY,
                candidate_exposure=123.45,  # type: ignore - float not allowed
            )
        assert "monetary values must be Decimal" in str(exc_info.value)

    def test_hypothesis_candidate_exposure_accepts_decimal(self):
        hyp = Hypothesis(
            claim="test",
            category=HypothesisCategory.VENDOR_INTEGRITY,
            candidate_exposure=Decimal("123.45"),
        )
        assert hyp.candidate_exposure == Decimal("123.45")

    def test_hypothesis_candidate_exposure_accepts_int(self):
        hyp = Hypothesis(
            claim="test",
            category=HypothesisCategory.VENDOR_INTEGRITY,
            candidate_exposure=123,  # type: ignore
        )
        assert hyp.candidate_exposure == 123

    def test_hypothesis_candidate_exposure_accepts_string(self):
        # String values are converted to Decimal by Pydantic
        hyp = Hypothesis(
            claim="test",
            category=HypothesisCategory.VENDOR_INTEGRITY,
            candidate_exposure="123.45",  # type: ignore
        )
        assert hyp.candidate_exposure == Decimal("123.45")

    def test_tool_calculation_result_rejects_float(self):
        with pytest.raises(ValidationError) as exc_info:
            ToolCalculation(
                expression="1+1",
                result=2.0,  # type: ignore - float not allowed
            )
        assert "monetary values must be Decimal" in str(exc_info.value)

    def test_tool_calculation_result_accepts_decimal(self):
        calc = ToolCalculation(
            expression="1+1",
            result=Decimal("2"),
        )
        assert calc.result == Decimal("2")

    def test_tool_calculation_input_value_rejects_float(self):
        with pytest.raises(ValidationError) as exc_info:
            ToolCalculationInput(
                label="test",
                value=10.5,  # type: ignore - float not allowed
                evidence_id="eid",
            )
        assert "monetary values must be Decimal" in str(exc_info.value)

    def test_tool_calculation_input_value_accepts_decimal(self):
        inp = ToolCalculationInput(
            label="test",
            value=Decimal("10.5"),
            evidence_id="eid",
        )
        assert inp.value == Decimal("10.5")


class TestHypothesisConstruction:
    """Test Hypothesis construction with valid data."""

    def test_minimal_hypothesis(self):
        hyp = Hypothesis(
            claim="A test claim",
            category=HypothesisCategory.VENDOR_INTEGRITY,
        )
        assert hyp.claim == "A test claim"
        assert hyp.category == HypothesisCategory.VENDOR_INTEGRITY
        assert hyp.status == HypothesisStatus.PROPOSED
        assert hyp.priority == 0
        assert hyp.supporting_evidence_ids == []
        assert hyp.candidate_exposure is None
        assert hyp.verdict_recommendation == VerdictRecommendation.UNDECIDED

    def test_hypothesis_with_all_fields(self):
        hyp_id = uuid4()
        hyp = Hypothesis(
            hypothesis_id=hyp_id,
            claim="A comprehensive claim",
            category=HypothesisCategory.SPLIT_PAYMENT,
            status=HypothesisStatus.ACTIVE,
            priority=42,
            supporting_evidence_ids=["e1", "e2"],
            contradicting_evidence_ids=["e3"],
            missing_evidence=["e4"],
            candidate_exposure=Decimal("1000.50"),
            next_actions=["action1"],
            verdict_recommendation=VerdictRecommendation.CONFIRM,
            subject="vendor_xyz",
        )
        assert hyp.hypothesis_id == hyp_id
        assert hyp.claim == "A comprehensive claim"
        assert hyp.category == HypothesisCategory.SPLIT_PAYMENT
        assert hyp.status == HypothesisStatus.ACTIVE
        assert hyp.priority == 42
        assert hyp.supporting_evidence_ids == ["e1", "e2"]
        assert hyp.contradicting_evidence_ids == ["e3"]
        assert hyp.missing_evidence == ["e4"]
        assert hyp.candidate_exposure == Decimal("1000.50")
        assert hyp.next_actions == ["action1"]
        assert hyp.verdict_recommendation == VerdictRecommendation.CONFIRM
        assert hyp.subject == "vendor_xyz"


class TestInvestigationConstruction:
    """Test Investigation construction with valid data."""

    def test_minimal_investigation(self):
        now = datetime.now(UTC)
        inv = Investigation(
            engagement_id="eng1",
            objective="Find fraud",
            created_at=now,
            updated_at=now,
        )
        assert inv.engagement_id == "eng1"
        assert inv.objective == "Find fraud"
        assert inv.status == InvestigationStatus.PLANNING
        assert inv.hypotheses == []
        assert inv.completed_actions == []
        assert inv.evidence_ids == []

    def test_investigation_with_hypotheses(self):
        now = datetime.now(UTC)
        hyp1 = Hypothesis(
            claim="Claim 1",
            category=HypothesisCategory.VENDOR_INTEGRITY,
            priority=10,
        )
        hyp2 = Hypothesis(
            claim="Claim 2",
            category=HypothesisCategory.CAPITALISATION,
            priority=5,
        )
        inv = Investigation(
            engagement_id="eng1",
            objective="Find fraud",
            status=InvestigationStatus.ACTIVE,
            hypotheses=[hyp1, hyp2],
            created_at=now,
            updated_at=now,
        )
        assert len(inv.hypotheses) == 2
        assert inv.hypotheses[0].claim == "Claim 1"
        assert inv.hypotheses[1].claim == "Claim 2"
        assert inv.status == InvestigationStatus.ACTIVE


class TestInvestigationHypothesisLookup:
    """Test Investigation.hypothesis() method."""

    def test_hypothesis_lookup_by_uuid(self):
        now = datetime.now(UTC)
        hyp_id = uuid4()
        hyp = Hypothesis(
            hypothesis_id=hyp_id,
            claim="Test",
            category=HypothesisCategory.CUTOFF,
        )
        inv = Investigation(
            engagement_id="eng1",
            objective="Test",
            hypotheses=[hyp],
            created_at=now,
            updated_at=now,
        )
        found = inv.hypothesis(hyp_id)
        assert found is not None
        assert found.hypothesis_id == hyp_id

    def test_hypothesis_lookup_by_string(self):
        now = datetime.now(UTC)
        hyp_id = uuid4()
        hyp = Hypothesis(
            hypothesis_id=hyp_id,
            claim="Test",
            category=HypothesisCategory.CUTOFF,
        )
        inv = Investigation(
            engagement_id="eng1",
            objective="Test",
            hypotheses=[hyp],
            created_at=now,
            updated_at=now,
        )
        found = inv.hypothesis(str(hyp_id))
        assert found is not None
        assert found.hypothesis_id == hyp_id

    def test_hypothesis_lookup_not_found(self):
        now = datetime.now(UTC)
        inv = Investigation(
            engagement_id="eng1",
            objective="Test",
            created_at=now,
            updated_at=now,
        )
        found = inv.hypothesis(uuid4())
        assert found is None
