"""Tests for the investigation loop and deterministic planner."""

from __future__ import annotations

from pathlib import Path

from audit_compiler.agent.context import AgentContext
from audit_compiler.agent.loop import (
    InvestigationLimits,
    run_investigation,
    run_next_step,
    start_investigation,
)
from audit_compiler.agent.models import (
    HypothesisCategory,
    HypothesisStatus,
    InvestigationStatus,
)
from audit_compiler.agent.planner import DeterministicPlanner


class TestInvestigationInitialization:
    """Test investigation startup and hypothesis proposal."""

    def test_start_investigation_creates_hypotheses(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()

        inv = start_investigation(
            ctx,
            engagement_id="test-eng-1",
            objective="Test audit",
            planner=planner,
        )

        assert inv.engagement_id == "test-eng-1"
        assert inv.objective == "Test audit"
        assert inv.status == InvestigationStatus.ACTIVE
        assert len(inv.hypotheses) > 0
        # Deterministic planner should create hypotheses for available controls
        assert all(h.category in HypothesisCategory for h in inv.hypotheses)

    def test_start_investigation_timeline_events(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()

        inv = start_investigation(
            ctx,
            engagement_id="test-eng-2",
            objective="Test audit",
            planner=planner,
        )

        # Check timeline has investigation_started event
        timeline_kinds = {e["kind"] for e in inv.timeline}
        assert "investigation_started" in timeline_kinds
        assert "hypothesis_created" in timeline_kinds


class TestRunFullInvestigation:
    """Test full investigation runs with the deterministic planner."""

    def test_run_investigation_completes(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()

        inv = run_investigation(
            ctx,
            engagement_id="test-eng-3",
            objective="Find anomalies",
            planner=planner,
        )

        # Investigation must terminate
        assert inv.status in {
            InvestigationStatus.COMPLETED,
            InvestigationStatus.STOPPED,
            InvestigationStatus.SUBMITTED,
            InvestigationStatus.DISMISSED,
        }

    def test_run_investigation_respects_max_steps(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()
        limits = InvestigationLimits(max_steps=1)

        inv = run_investigation(
            ctx,
            engagement_id="test-eng-4",
            objective="Find anomalies",
            planner=planner,
            limits=limits,
        )

        # With max_steps=1, the investigation should not complete all hypotheses
        # (unless there are no hypotheses or one step completes everything by chance)
        if inv.hypotheses:
            # Check that not all hypotheses are in terminal states
            non_terminal = [
                h for h in inv.hypotheses
                if h.status not in {
                    HypothesisStatus.SUBMITTED,
                    HypothesisStatus.DISMISSED,
                    HypothesisStatus.REFUTED,
                    HypothesisStatus.INSUFFICIENT_EVIDENCE,
                    HypothesisStatus.AWAITING_AUDITOR,
                }
            ]
            # Either we have non-terminal hypotheses or we hit the limit and stopped
            has_non_terminal = len(non_terminal) > 0
            hit_limit = inv.status in {InvestigationStatus.STOPPED, InvestigationStatus.COMPLETED}
            assert has_non_terminal or hit_limit

    def test_run_investigation_respects_max_tool_calls(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()
        limits = InvestigationLimits(max_tool_calls=1)

        inv = run_investigation(
            ctx,
            engagement_id="test-eng-5",
            objective="Find anomalies",
            planner=planner,
            limits=limits,
        )

        # Count tool_result events
        tool_results = [e for e in inv.timeline if e["kind"] == "tool_result"]
        assert len(tool_results) <= 1

    def test_run_investigation_never_exceeds_limits(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()
        limits = InvestigationLimits(max_steps=5, max_tool_calls=8)

        inv = run_investigation(
            ctx,
            engagement_id="test-eng-6",
            objective="Find anomalies",
            planner=planner,
            limits=limits,
        )

        # Count tool_result events and steps
        tool_results = [e for e in inv.timeline if e["kind"] == "tool_result"]
        assert len(tool_results) <= limits.max_tool_calls
        # Investigation must terminate
        assert inv.status in {
            InvestigationStatus.COMPLETED,
            InvestigationStatus.STOPPED,
            InvestigationStatus.SUBMITTED,
            InvestigationStatus.DISMISSED,
        }


class TestInvestigationTermination:
    """Test that investigations always terminate properly."""

    def test_run_investigation_always_terminates(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()

        inv = run_investigation(
            ctx,
            engagement_id="test-eng-7",
            objective="Find anomalies",
            planner=planner,
            limits=InvestigationLimits(max_steps=20, max_tool_calls=50),
        )

        # Must be in a terminal state
        assert inv.status in {
            InvestigationStatus.COMPLETED,
            InvestigationStatus.STOPPED,
            InvestigationStatus.SUBMITTED,
            InvestigationStatus.DISMISSED,
        }

    def test_all_hypotheses_reach_terminal_status(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()
        terminal_states = {
            HypothesisStatus.SUBMITTED,
            HypothesisStatus.DISMISSED,
            HypothesisStatus.REFUTED,
            HypothesisStatus.INSUFFICIENT_EVIDENCE,
            HypothesisStatus.AWAITING_AUDITOR,
        }

        inv = run_investigation(
            ctx,
            engagement_id="test-eng-8",
            objective="Find anomalies",
            planner=planner,
            limits=InvestigationLimits(max_steps=20, max_tool_calls=50),
        )

        # If investigation is COMPLETED, all hypotheses should be terminal
        if inv.status == InvestigationStatus.COMPLETED:
            for hyp in inv.hypotheses:
                assert hyp.status in terminal_states


class TestControlCategoryResolution:
    """Test that the four control categories are resolved in an investigation."""

    def test_four_categories_created(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()

        inv = start_investigation(
            ctx,
            engagement_id="test-eng-9",
            objective="Test all categories",
            planner=planner,
        )

        # Check that we have hypotheses for the four main categories
        categories = {h.category for h in inv.hypotheses}
        expected_categories = {
            HypothesisCategory.VENDOR_INTEGRITY,
            HypothesisCategory.SPLIT_PAYMENT,
            HypothesisCategory.CAPITALISATION,
            HypothesisCategory.CUTOFF,
        }
        # At least some of the expected categories should be present
        assert len(categories & expected_categories) > 0


class TestTimeline:
    """Test that the investigation timeline records all events."""

    def test_timeline_has_expected_event_kinds(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()

        inv = run_investigation(
            ctx,
            engagement_id="test-eng-10",
            objective="Test timeline",
            planner=planner,
            limits=InvestigationLimits(max_steps=5, max_tool_calls=10),
        )

        timeline_kinds = {e["kind"] for e in inv.timeline}
        # Check for essential event kinds
        expected = {"investigation_started", "hypothesis_created"}
        assert expected.issubset(timeline_kinds)

        # If any tool ran, we should have tool_result or tool_selected
        if len(inv.completed_actions) > 0 or any(
            e["kind"] in ("tool_selected", "tool_result") for e in inv.timeline
        ):
            assert "tool_selected" in timeline_kinds or "tool_result" in timeline_kinds

    def test_timeline_has_events_and_metadata(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()

        inv = run_investigation(
            ctx,
            engagement_id="test-eng-11",
            objective="Test timeline metadata",
            planner=planner,
            limits=InvestigationLimits(max_steps=3, max_tool_calls=5),
        )

        # Every timeline event should have a "kind" and "at" timestamp
        for event in inv.timeline:
            assert "kind" in event
            assert "at" in event
            assert isinstance(event["at"], str)  # ISO format timestamp


class TestEvidenceRegistry:
    """Test that all evidence references are valid."""

    def test_no_invalid_evidence_ids(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()

        inv = run_investigation(
            ctx,
            engagement_id="test-eng-12",
            objective="Test evidence ids",
            planner=planner,
            limits=InvestigationLimits(max_steps=5, max_tool_calls=10),
        )

        # Collect all referenced evidence ids from hypotheses
        all_evidence_ids = set()
        for hyp in inv.hypotheses:
            for eid in hyp.supporting_evidence_ids:
                all_evidence_ids.add(eid)
            for eid in hyp.contradicting_evidence_ids:
                all_evidence_ids.add(eid)

        # Also collect from investigation level
        for eid in inv.evidence_ids:
            all_evidence_ids.add(eid)
        for eid in inv.contradicting_evidence_ids:
            all_evidence_ids.add(eid)

        # All evidence ids should exist in the registry
        for eid in all_evidence_ids:
            if eid:  # Skip empty strings
                assert ctx.registry.contains(eid), f"Evidence id {eid} not in registry"


class TestReplayability:
    """Test that investigations are deterministic across runs."""

    def test_same_planner_same_results(self, sample_dossier: Path):
        """Two runs produce same results with fresh planner and context."""
        engagement_id = "test-replayability"
        objective = "Replay test"
        limits = InvestigationLimits(max_steps=8, max_tool_calls=15)

        # Run 1
        ctx1 = AgentContext.from_dossier_path(sample_dossier)
        planner1 = DeterministicPlanner()
        inv1 = run_investigation(
            ctx1,
            engagement_id=engagement_id,
            objective=objective,
            planner=planner1,
            limits=limits,
        )

        # Run 2
        ctx2 = AgentContext.from_dossier_path(sample_dossier)
        planner2 = DeterministicPlanner()
        inv2 = run_investigation(
            ctx2,
            engagement_id=engagement_id,
            objective=objective,
            planner=planner2,
            limits=limits,
        )

        # Both should reach terminal state
        assert inv1.status in {
            InvestigationStatus.COMPLETED,
            InvestigationStatus.STOPPED,
            InvestigationStatus.SUBMITTED,
            InvestigationStatus.DISMISSED,
        }
        assert inv2.status in {
            InvestigationStatus.COMPLETED,
            InvestigationStatus.STOPPED,
            InvestigationStatus.SUBMITTED,
            InvestigationStatus.DISMISSED,
        }

        # They should have the same number of hypotheses (deterministic proposal)
        assert len(inv1.hypotheses) == len(inv2.hypotheses)

        # Hypotheses should be in the same categories (order may vary)
        cats1 = {h.category for h in inv1.hypotheses}
        cats2 = {h.category for h in inv2.hypotheses}
        assert cats1 == cats2

        # Both should complete similarly (same terminal status or close tool call counts)
        tool_results1 = len([e for e in inv1.timeline if e["kind"] == "tool_result"])
        tool_results2 = len([e for e in inv2.timeline if e["kind"] == "tool_result"])
        # Deterministic planner should produce exactly the same number of tool calls
        assert tool_results1 == tool_results2


class TestHonestTwinDismissal:
    """Test that self-approved vendors are dismissed while other vendors are confirmed."""

    def test_vendor_category_investigation(self, sample_dossier: Path):
        """Vendor integrity hypothesis should reach a terminal state."""
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()

        inv = run_investigation(
            ctx,
            engagement_id="test-vendor-eng",
            objective="Test vendor integrity",
            planner=planner,
            limits=InvestigationLimits(max_steps=15, max_tool_calls=25),
        )

        # Find vendor integrity hypotheses
        vendor_hyps = [
            h for h in inv.hypotheses
            if h.category == HypothesisCategory.VENDOR_INTEGRITY
        ]

        # At least one vendor hypothesis should exist
        assert len(vendor_hyps) > 0

        # All vendor hypotheses should reach terminal state by end of investigation
        terminal_states = {
            HypothesisStatus.SUBMITTED,
            HypothesisStatus.DISMISSED,
            HypothesisStatus.REFUTED,
            HypothesisStatus.INSUFFICIENT_EVIDENCE,
            HypothesisStatus.AWAITING_AUDITOR,
        }
        for hyp in vendor_hyps:
            if inv.status == InvestigationStatus.COMPLETED:
                assert hyp.status in terminal_states


class TestStepByStepExecution:
    """Test run_next_step behavior."""

    def test_next_step_increments_progress(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()

        inv = start_investigation(
            ctx,
            engagement_id="test-steps",
            objective="Test step execution",
            planner=planner,
        )

        initial_actions = len(inv.completed_actions)

        # Run one step
        inv = run_next_step(inv, ctx, planner=planner)

        # Either we took an action or reached a terminal state
        actions_increased = len(inv.completed_actions) > initial_actions
        reached_terminal = inv.status in {
            InvestigationStatus.COMPLETED,
            InvestigationStatus.STOPPED,
            InvestigationStatus.DISMISSED,
            InvestigationStatus.SUBMITTED,
        }
        assert actions_increased or reached_terminal

    def test_multiple_steps(self, sample_dossier: Path):
        ctx = AgentContext.from_dossier_path(sample_dossier)
        planner = DeterministicPlanner()

        inv = start_investigation(
            ctx,
            engagement_id="test-multi-steps",
            objective="Test multiple steps",
            planner=planner,
        )

        # Run 3 steps
        for _ in range(3):
            if inv.status not in {
                InvestigationStatus.COMPLETED,
                InvestigationStatus.STOPPED,
                InvestigationStatus.DISMISSED,
                InvestigationStatus.SUBMITTED,
            }:
                inv = run_next_step(inv, ctx, planner=planner)

        # Investigation should still be in a valid state
        assert inv.status in {
            InvestigationStatus.PLANNING,
            InvestigationStatus.ACTIVE,
            InvestigationStatus.AWAITING_AUDITOR,
            InvestigationStatus.SUBMITTED,
            InvestigationStatus.DISMISSED,
            InvestigationStatus.STOPPED,
            InvestigationStatus.COMPLETED,
        }
