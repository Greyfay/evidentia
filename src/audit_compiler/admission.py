"""Conservative, deterministic admission of control outcomes.

Controls produce candidates; this module alone assigns publication verdicts.  The
canonical :class:`~audit_compiler.models.ControlOutcome` is the only input capable of
confirmation.  The older dossier ``Finding`` is accepted during migration, but is
always routed conservatively unless counter-evidence dismisses it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

from audit_compiler.controls.base import Finding
from audit_compiler.models import (
    AdmissionReason,
    AdmissionReasonCode,
    ControlOutcome,
    CounterTest,
    CounterTestOutcome,
    EvidenceRef,
)

Verdict = Literal["CONFIRMED", "HUMAN_REVIEW", "DISMISSED", "REJECTED"]

_REASON_ORDER = {code: index for index, code in enumerate(AdmissionReasonCode)}
_DISPLAY = {
    AdmissionReasonCode.EVIDENCE_AND_CONTROLS_SUPPORT: (
        "Evidence and deterministic controls fully support the finding."
    ),
    AdmissionReasonCode.COUNTER_EVIDENCE_PRESENT: (
        "Supported counter-evidence resolves the allegation."
    ),
    AdmissionReasonCode.COUNTER_EVIDENCE_CONFLICTING: "Evidence is conflicting.",
    AdmissionReasonCode.COUNTER_TEST_INCOMPLETE: (
        "One or more required counter-tests are incomplete or unsupported."
    ),
    AdmissionReasonCode.MATERIAL_UNCERTAINTY: "Material uncertainty remains.",
    AdmissionReasonCode.ACCOUNTING_JUDGEMENT: "Accounting judgement is required.",
    AdmissionReasonCode.SUPPORTING_EVIDENCE_INCOMPLETE: (
        "Supporting evidence is incomplete."
    ),
    AdmissionReasonCode.EVIDENCE_CHAIN_MISSING: (
        "The evidence chain is missing, malformed, or unresolved."
    ),
    AdmissionReasonCode.CALCULATION_SUPPORT_MISSING: (
        "The calculation is uncited or cannot be replayed."
    ),
    AdmissionReasonCode.CONTROL_SUPPORT_MISSING: (
        "No valid deterministic control supports the assertion."
    ),
}


def _reason_key(reason: AdmissionReason) -> tuple[int, str, tuple[str, ...]]:
    return (
        _REASON_ORDER[reason.code],
        reason.detail or "",
        tuple(str(item) for item in reason.evidence_ids),
    )


def _ordered(reasons: list[AdmissionReason]) -> tuple[AdmissionReason, ...]:
    unique = {
        (reason.code, reason.detail, reason.evidence_ids): reason for reason in reasons
    }
    return tuple(sorted(unique.values(), key=_reason_key))


def _display_text(reasons: tuple[AdmissionReason, ...]) -> str:
    return " ".join(_DISPLAY[reason.code] for reason in reasons)


@dataclass(frozen=True)
class Admission:
    verdict: Verdict
    reasons: tuple[AdmissionReason, ...]

    @property
    def reason(self) -> str:
        """Human-readable text derived exclusively from structured reasons."""

        return _display_text(self.reasons)

    def deterministic_json(self) -> str:
        """Serialize the decision independently of candidate input order."""

        import json

        return json.dumps(
            {
                "reason": self.reason,
                "reasons": [item.model_dump(mode="json") for item in self.reasons],
                "verdict": self.verdict,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def _make_reason(
    code: AdmissionReasonCode,
    detail: str | None = None,
    evidence_ids: tuple[UUID, ...] = (),
) -> AdmissionReason:
    return AdmissionReason(code=code, detail=detail, evidence_ids=evidence_ids)


def _evidence_index(refs: tuple[EvidenceRef, ...]) -> tuple[dict[UUID, EvidenceRef], bool]:
    index: dict[UUID, EvidenceRef] = {}
    inconsistent = False
    for ref in refs:
        previous = index.get(ref.evidence_id)
        if previous is not None and previous != ref:
            inconsistent = True
        index[ref.evidence_id] = ref
    return index, inconsistent


def _valid_search(counter: CounterTest, available: set[UUID]) -> bool:
    search = counter.search
    return bool(
        search is not None
        and search.scope.strip()
        and search.method.strip()
        and search.searched_sources
        and search.evidence_ids
        and set(search.evidence_ids) <= available
        and set(search.evidence_ids) <= {ref.evidence_id for ref in counter.evidence}
    )


def _counter_reasons(
    counters: tuple[CounterTest, ...], available: set[UUID]
) -> tuple[list[AdmissionReason], list[AdmissionReason]]:
    dismiss: list[AdmissionReason] = []
    review: list[AdmissionReason] = []
    for counter in sorted(counters, key=lambda item: (item.name, item.outcome.value)):
        evidence_ids = tuple(ref.evidence_id for ref in counter.evidence)
        evidence_valid = bool(evidence_ids) and set(evidence_ids) <= available
        detail = counter.name
        if counter.outcome == CounterTestOutcome.PRESENT:
            if evidence_valid:
                dismiss.append(
                    _make_reason(
                        AdmissionReasonCode.COUNTER_EVIDENCE_PRESENT,
                        detail,
                        evidence_ids,
                    )
                )
            elif counter.required:
                review.append(
                    _make_reason(AdmissionReasonCode.COUNTER_TEST_INCOMPLETE, detail)
                )
        elif counter.outcome == CounterTestOutcome.CONFLICTING:
            review.append(
                _make_reason(
                    AdmissionReasonCode.COUNTER_EVIDENCE_CONFLICTING,
                    detail,
                    evidence_ids if evidence_valid else (),
                )
            )
        elif not counter.required:
            continue
        elif counter.outcome == CounterTestOutcome.SEARCHED_ABSENT:
            if not _valid_search(counter, available):
                review.append(
                    _make_reason(AdmissionReasonCode.COUNTER_TEST_INCOMPLETE, detail)
                )
        elif counter.outcome in {
            CounterTestOutcome.UNKNOWN,
            CounterTestOutcome.NOT_EXECUTED,
        }:
            review.append(
                _make_reason(AdmissionReasonCode.COUNTER_TEST_INCOMPLETE, detail)
            )
        elif counter.outcome == CounterTestOutcome.NOT_APPLICABLE:
            # A required test may be inapplicable only when the justification itself is cited.
            if not counter.detail.strip() or not evidence_valid:
                review.append(
                    _make_reason(AdmissionReasonCode.COUNTER_TEST_INCOMPLETE, detail)
                )
    return dismiss, review


def _admit_canonical(outcome: ControlOutcome) -> Admission:
    reject: list[AdmissionReason] = []
    refs = tuple(outcome.evidence_refs)
    index, inconsistent_refs = _evidence_index(refs)
    available = set(index)

    if not refs or inconsistent_refs:
        reject.append(_make_reason(AdmissionReasonCode.EVIDENCE_CHAIN_MISSING))
    if (
        not outcome.control_id.strip()
        or not outcome.control_version.strip()
        or outcome.control_id == "legacy"
        or outcome.control_version == "legacy"
    ):
        reject.append(_make_reason(AdmissionReasonCode.CONTROL_SUPPORT_MISSING))

    calculation = outcome.calculation
    cited_ids = {item.evidence_id for item in calculation.inputs}
    calculation_bad = bool(
        not calculation.expression.strip()
        or not calculation.inputs
        or not cited_ids <= available
        or calculation.result != outcome.exposure_amount
    )
    replay = outcome.replay
    if replay is None:
        calculation_bad = True
    else:
        replay_ids = set(replay.evidence_ids)
        binding_ids = {item.evidence_id for item in replay.bindings}
        input_names = {item.name for item in replay.inputs}
        binding_names = {item.name for item in replay.bindings}
        calculation_bad |= bool(
            replay.engagement_id != outcome.engagement_id
            or replay.run_id != outcome.run_id
            or replay.control_id != outcome.control_id
            or replay.control_version != outcome.control_version
            or replay.engagement_id == "legacy"
            or replay.run_id == "legacy"
            or not replay.runtime_version.strip()
            or not replay.inputs
            or not replay.evidence_ids
            or not replay.bindings
            or not replay_ids <= available
            or not binding_ids <= replay_ids
            or not cited_ids <= replay_ids
            or not input_names <= binding_names
        )
        if calculation.sql.strip():
            calculation_bad |= not bool(replay.bindings)
        else:
            calculation_bad |= not bool(calculation.expression.strip() and cited_ids)
    if calculation_bad:
        reject.append(_make_reason(AdmissionReasonCode.CALCULATION_SUPPORT_MISSING))

    # Counter-test citations are part of the evidence chain too.  An unresolved claimed
    # citation is malformed, regardless of which later transition it might suggest.
    counter_ids = {
        ref.evidence_id for counter in outcome.counter_tests for ref in counter.evidence
    }
    search_ids = {
        evidence_id
        for counter in outcome.counter_tests
        if counter.search is not None
        for evidence_id in counter.search.evidence_ids
    }
    if not counter_ids <= available or not search_ids <= available:
        reject.append(_make_reason(AdmissionReasonCode.EVIDENCE_CHAIN_MISSING))

    if reject:
        reasons = _ordered(reject)
        return Admission("REJECTED", reasons)

    dismiss, review = _counter_reasons(outcome.counter_tests, available)
    if dismiss:
        return Admission("DISMISSED", _ordered(dismiss))

    signals = outcome.admission_signals
    if signals.conflicting_evidence:
        review.append(_make_reason(AdmissionReasonCode.COUNTER_EVIDENCE_CONFLICTING))
    if signals.material_uncertainty or outcome.uncertainty:
        review.append(_make_reason(AdmissionReasonCode.MATERIAL_UNCERTAINTY))
    if signals.accounting_judgement:
        review.append(_make_reason(AdmissionReasonCode.ACCOUNTING_JUDGEMENT))
    if signals.incomplete_supporting_evidence:
        review.append(_make_reason(AdmissionReasonCode.SUPPORTING_EVIDENCE_INCOMPLETE))
    if not outcome.counter_tests or not any(counter.required for counter in outcome.counter_tests):
        review.append(_make_reason(AdmissionReasonCode.COUNTER_TEST_INCOMPLETE))
    if review:
        return Admission("HUMAN_REVIEW", _ordered(review))

    return Admission(
        "CONFIRMED",
        (_make_reason(AdmissionReasonCode.EVIDENCE_AND_CONTROLS_SUPPORT),),
    )


def _admit_legacy(finding: Finding) -> Admission:
    reject: list[AdmissionReason] = []
    if not finding.evidence_chain or any(
        not step.step or not step.evidence for step in finding.evidence_chain
    ):
        reject.append(_make_reason(AdmissionReasonCode.EVIDENCE_CHAIN_MISSING))
    if not finding.control_id.strip():
        reject.append(_make_reason(AdmissionReasonCode.CONTROL_SUPPORT_MISSING))
    if (
        finding.exposure != Decimal(0)
        and not finding.calculation.inputs
        or not finding.calculation.expression.strip()
    ):
        reject.append(_make_reason(AdmissionReasonCode.CALCULATION_SUPPORT_MISSING))
    if reject:
        return Admission("REJECTED", _ordered(reject))

    present = sorted(
        (
            counter
            for counter in finding.counter_tests
            if counter.required and counter.outcome == "present" and counter.evidence
        ),
        key=lambda counter: counter.name,
    )
    if present:
        counter = present[0]
        return Admission(
            "DISMISSED",
            (
                _make_reason(
                    AdmissionReasonCode.COUNTER_EVIDENCE_PRESENT,
                    counter.name,
                    tuple(ref.evidence_id for ref in counter.evidence),
                ),
            ),
        )

    reasons = [_make_reason(AdmissionReasonCode.COUNTER_TEST_INCOMPLETE, "legacy input")]
    if finding.uncertainty:
        reasons.append(_make_reason(AdmissionReasonCode.MATERIAL_UNCERTAINTY))
    return Admission("HUMAN_REVIEW", _ordered(reasons))


def admit(candidate: ControlOutcome | Finding) -> Admission:
    """Apply admission precedence without consulting proposed statuses or verdicts."""

    if isinstance(candidate, ControlOutcome):
        return _admit_canonical(candidate)
    if isinstance(candidate, Finding):
        return _admit_legacy(candidate)
    return Admission(
        "REJECTED", (_make_reason(AdmissionReasonCode.CONTROL_SUPPORT_MISSING),)
    )
