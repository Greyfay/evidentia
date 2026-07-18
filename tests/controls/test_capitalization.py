from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from audit_compiler.controls import (
    AccountClassification,
    AssetDescriptionRecord,
    CapitalizationControl,
    CapitalizationInvoiceRecord,
    CapitalizationParameters,
    CapitalizationSignalType,
    CapitalizationSupportKind,
    CapitalizationSupportRecord,
    CapitalizationVocabulary,
    Control,
    ControlContext,
    CounterTestStatus,
    FixedAssetAdditionRecord,
    GeneralLedgerPostingRecord,
    OutcomeStatus,
)
from audit_compiler.models import EvidenceRef, SourceType


def _evidence(row: int, value: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            source_path="synthetic/capitalization.csv",
            source_type=SourceType.CSV_ROW,
            file_sha256="c" * 64,
            raw_value=value,
            row=row,
        ),
    )


def _addition(
    addition_id: str,
    description: str,
    *,
    row: int = 1,
    amount: str = "1250.00",
    asset_id: str = "asset-one",
    vendor_id: str | None = "vendor-one",
    addition_date: date = date(2026, 2, 1),
    category: str | None = "equipment",
) -> FixedAssetAdditionRecord:
    return FixedAssetAdditionRecord(
        record_id=f"addition-record-{addition_id}",
        addition_id=addition_id,
        asset_id=asset_id,
        vendor_id=vendor_id,
        addition_date=addition_date,
        net_amount=Decimal(amount),
        description=description,
        category=category,
        evidence_refs=_evidence(row, f"{description}|{category or ''}"),
    )


def _posting(
    addition_id: str,
    description: str,
    *,
    row: int = 2,
    amount: str = "1250.00",
    posting_id: str | None = None,
    account_classification: AccountClassification = AccountClassification.ASSET,
    reversal_of: str | None = None,
    is_reclassification: bool = False,
) -> GeneralLedgerPostingRecord:
    resolved_id = posting_id or f"posting-{addition_id}"
    return GeneralLedgerPostingRecord(
        record_id=f"posting-record-{resolved_id}",
        posting_id=resolved_id,
        addition_id=addition_id,
        account_id="account-one",
        account_classification=account_classification,
        posting_date=date(2026, 2, 2),
        amount=Decimal(amount),
        description=description,
        evidence_refs=_evidence(row, description),
        reversal_of_posting_id=reversal_of,
        is_reclassification=is_reclassification,
    )


def _invoice(
    addition_id: str,
    description: str,
    *,
    row: int = 3,
    amount: str | None = "1250.00",
) -> CapitalizationInvoiceRecord:
    return CapitalizationInvoiceRecord(
        record_id=f"invoice-record-{addition_id}",
        invoice_id=f"invoice-{addition_id}",
        addition_id=addition_id,
        invoice_date=date(2026, 1, 31),
        net_amount=Decimal(amount) if amount is not None else None,
        description=description,
        evidence_refs=_evidence(row, description),
    )


def _asset(
    asset_id: str,
    description: str,
    *,
    row: int = 4,
    distinct: bool | None = None,
) -> AssetDescriptionRecord:
    return AssetDescriptionRecord(
        record_id=f"asset-record-{asset_id}",
        asset_id=asset_id,
        description=description,
        category="production equipment",
        distinct_new_asset=distinct,
        evidence_refs=_evidence(row, description),
    )


def _support(
    addition_id: str,
    kind: CapitalizationSupportKind,
    *,
    row: int,
    present: bool = True,
) -> CapitalizationSupportRecord:
    return CapitalizationSupportRecord(
        record_id=f"support-{addition_id}-{kind.value}",
        addition_id=addition_id,
        kind=kind,
        present=present,
        evidence_refs=_evidence(row, kind.value),
    )


def _evaluate(
    records: tuple,
    parameters: CapitalizationParameters | None = None,
):
    return CapitalizationControl().evaluate(
        ControlContext(
            records=records,
            parameters=parameters or CapitalizationParameters(),
        )
    )


def _signal_types(outcome) -> set[CapitalizationSignalType]:
    return {signal.signal_type for signal in outcome.signals}


def _counter(outcome, kind: CapitalizationSupportKind):
    return next(test for test in outcome.counter_tests if test.name == kind.value)


def test_ordinary_repair_capitalized_is_review_needed_and_replayable() -> None:
    records = (
        _addition("addition-one", "Routine repair and maintenance"),
        _posting("addition-one", "Capitalized repair"),
        _invoice("addition-one", "Maintenance work"),
    )

    outcome = _evaluate(records)[0]

    assert isinstance(CapitalizationControl(), Control)
    assert outcome.status == OutcomeStatus.REVIEW_NEEDED
    assert outcome.capitalized_net_amount == Decimal("1250.00")
    assert outcome.exposure_amount == Decimal("1250.00")
    assert CapitalizationSignalType.REPAIR_OR_MAINTENANCE_LANGUAGE in _signal_types(
        outcome
    )
    assert CapitalizationSignalType.POSTED_TO_ASSET_ACCOUNT in _signal_types(outcome)
    assert outcome.calculation_steps[0].result == "1250.00"
    assert outcome.calculation_steps[2].result == "representations_not_added_to_exposure"
    assert all(signal.evidence_refs for signal in outcome.signals)
    assert all(step.evidence_refs for step in outcome.calculation_steps)
    assert "confirmed" not in outcome.status.value


def test_genuine_new_machine_acquisition_is_dismissed_by_counter_evidence() -> None:
    records = (
        _addition("addition-new", "Acquisition of production equipment"),
        _posting("addition-new", "Equipment acquisition"),
        _asset("asset-one", "Distinct new production machine", distinct=True),
        _support(
            "addition-new", CapitalizationSupportKind.INVESTMENT_APPROVAL, row=5
        ),
        _support("addition-new", CapitalizationSupportKind.PROJECT_REFERENCE, row=6),
    )

    outcome = _evaluate(records)[0]

    assert outcome.status == OutcomeStatus.DISMISSED
    assert _counter(
        outcome, CapitalizationSupportKind.DISTINCT_NEW_ASSET
    ).status == CounterTestStatus.ACCOUNTED_FOR
    assert _counter(
        outcome, CapitalizationSupportKind.INVESTMENT_APPROVAL
    ).status == CounterTestStatus.ACCOUNTED_FOR
    assert outcome.exposure_amount == Decimal("1250.00")


def test_major_component_with_useful_life_evidence_is_dismissed() -> None:
    records = (
        _addition("addition-component", "Replacement of main drive component"),
        _posting("addition-component", "Major component replacement"),
        _support(
            "addition-component",
            CapitalizationSupportKind.SEPARABLE_MAJOR_COMPONENT,
            row=5,
        ),
        _support(
            "addition-component",
            CapitalizationSupportKind.USEFUL_LIFE_EXTENSION,
            row=6,
        ),
    )

    outcome = _evaluate(records)[0]

    assert outcome.status == OutcomeStatus.DISMISSED
    assert (
        CapitalizationSignalType.REPLACEMENT_OVERHAUL_SERVICE_LANGUAGE
        in _signal_types(outcome)
    )
    assert _counter(
        outcome, CapitalizationSupportKind.SEPARABLE_MAJOR_COMPONENT
    ).status == CounterTestStatus.ACCOUNTED_FOR
    assert _counter(
        outcome, CapitalizationSupportKind.USEFUL_LIFE_EXTENSION
    ).status == CounterTestStatus.ACCOUNTED_FOR


def test_ambiguous_overhaul_requires_human_accounting_judgement() -> None:
    records = (
        _addition("addition-overhaul", "Overhaul of existing production line"),
        _posting("addition-overhaul", "Capitalized overhaul"),
    )

    outcome = _evaluate(records)[0]

    assert outcome.status == OutcomeStatus.REVIEW_NEEDED
    assert (
        CapitalizationSignalType.REPLACEMENT_OVERHAUL_SERVICE_LANGUAGE
        in _signal_types(outcome)
    )
    assert any("accounting judgement" in item for item in outcome.uncertainty)
    assert outcome.status != OutcomeStatus.CONFIRMED_CANDIDATE


def test_duplicate_representations_do_not_inflate_exposure_or_signal_count() -> None:
    addition = _addition("addition-duplicate", "Repair of existing equipment")
    posting = _posting("addition-duplicate", "Capitalized repair")
    invoice = _invoice("addition-duplicate", "Repair invoice")
    baseline = _evaluate((addition, posting, invoice))[0]

    duplicated = _evaluate(
        (invoice, addition, posting, addition, invoice, posting)
    )[0]

    assert duplicated == baseline
    assert duplicated.exposure_amount == Decimal("1250.00")
    assert duplicated.exposure_amount != Decimal("3750.00")
    assert len(duplicated.signals) == len(baseline.signals)


@pytest.mark.parametrize("use_reclassification", [False, True])
def test_reversed_or_reclassified_posting_clears_exposure(
    use_reclassification: bool,
) -> None:
    addition = _addition("addition-cleared", "Repair initially capitalized")
    original = _posting(
        "addition-cleared", "Original asset posting", posting_id="posting-original"
    )
    if use_reclassification:
        clearing = _posting(
            "addition-cleared",
            "Reclassification to expense",
            row=7,
            amount="-1250.00",
            posting_id="posting-clearing",
            is_reclassification=True,
        )
    else:
        clearing = _posting(
            "addition-cleared",
            "Reversal of asset posting",
            row=7,
            amount="-1250.00",
            posting_id="posting-clearing",
            reversal_of="posting-original",
        )

    outcome = _evaluate((addition, original, clearing))[0]

    assert outcome.status == OutcomeStatus.DISMISSED
    assert outcome.exposure_amount == Decimal("0")
    reversal = _counter(
        outcome, CapitalizationSupportKind.REVERSAL_OR_RECLASSIFICATION
    )
    assert reversal.status == CounterTestStatus.ACCOUNTED_FOR
    assert {evidence.row for evidence in reversal.evidence_refs} == {2, 7}


def test_german_and_english_terms_and_nearby_clusters_are_detected() -> None:
    records = (
        _addition(
            "addition-de",
            "Bestehende Anlage",
            row=10,
            addition_date=date(2026, 2, 1),
            category="Reparatur",
        ),
        _addition(
            "addition-en",
            "Maintenance of equipment",
            row=11,
            addition_date=date(2026, 2, 5),
        ),
    )

    outcomes = _evaluate(records)

    assert tuple(outcome.addition_id for outcome in outcomes) == (
        "ADDITION-DE",
        "ADDITION-EN",
    )
    assert all(
        CapitalizationSignalType.REPAIR_OR_MAINTENANCE_LANGUAGE
        in _signal_types(outcome)
        for outcome in outcomes
    )
    assert all(
        CapitalizationSignalType.MULTIPLE_REPAIR_LIKE_ADDITIONS
        in _signal_types(outcome)
        for outcome in outcomes
    )
    assert {term for outcome in outcomes for term in outcome.matched_trigger_terms} == {
        "maintenance",
        "reparatur",
    }


def test_results_are_independent_of_input_order() -> None:
    records = (
        _addition("addition-order", "Restoration of existing equipment"),
        _posting("addition-order", "Asset posting"),
        _invoice("addition-order", "Restoration services"),
        _support(
            "addition-order", CapitalizationSupportKind.INVESTMENT_APPROVAL, row=8
        ),
    )

    assert _evaluate(records) == _evaluate(tuple(reversed(records)))


def test_configurable_vocabulary_controls_matching() -> None:
    default_vocabulary = CapitalizationVocabulary()
    vocabulary = CapitalizationVocabulary(
        repair_maintenance_triggers=("refit",),
        replacement_overhaul_triggers=("renewal",),
        counter_evidence_terms=default_vocabulary.counter_evidence_terms,
    )
    weights = tuple(
        (
            signal,
            Decimal("7.5")
            if signal == CapitalizationSignalType.REPAIR_OR_MAINTENANCE_LANGUAGE
            else Decimal("1"),
        )
        for signal in CapitalizationSignalType
    )
    parameters = CapitalizationParameters(
        vocabulary=vocabulary,
        severity_weights=weights,
    )
    record = _addition("addition-config", "Refit of existing equipment")

    default_outcome = _evaluate((record,))[0]
    configured_outcome = _evaluate((record,), parameters)[0]

    assert (
        CapitalizationSignalType.REPAIR_OR_MAINTENANCE_LANGUAGE
        not in _signal_types(default_outcome)
    )
    assert (
        CapitalizationSignalType.REPAIR_OR_MAINTENANCE_LANGUAGE
        in _signal_types(configured_outcome)
    )
    assert configured_outcome.matched_trigger_terms == ("refit",)
    repair_signal = next(
        signal
        for signal in configured_outcome.signals
        if signal.signal_type
        == CapitalizationSignalType.REPAIR_OR_MAINTENANCE_LANGUAGE
    )
    assert repair_signal.weight == Decimal("7.5")
    assert (
        "counter_terms.distinct_new_asset",
        "new asset|neue anlage",
    ) in configured_outcome.rule_parameters


def test_missing_optional_evidence_remains_explicit_and_review_needed() -> None:
    outcome = _evaluate(
        (_addition("addition-missing", "Existing equipment servicing"),)
    )[0]

    assert outcome.status == OutcomeStatus.REVIEW_NEEDED
    assert {test.name for test in outcome.counter_tests} == {
        kind.value for kind in CapitalizationSupportKind
    }
    assert all(
        test.status == CounterTestStatus.UNRESOLVED for test in outcome.counter_tests
    )
    assert len(outcome.uncertainty) >= 2
    assert outcome.status != OutcomeStatus.CONFIRMED_CANDIDATE


def test_float_money_and_overlapping_vocabularies_are_rejected() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        FixedAssetAdditionRecord(
            record_id="record-invalid",
            addition_id="addition-invalid",
            asset_id="asset-invalid",
            vendor_id=None,
            addition_date=date(2026, 2, 1),
            net_amount=1.5,  # type: ignore[arg-type]
            description="repair",
            category=None,
            evidence_refs=_evidence(20, "invalid"),
        )

    with pytest.raises(ValueError, match="remain separate"):
        CapitalizationVocabulary(
            repair_maintenance_triggers=("repair",),
            replacement_overhaul_triggers=("overhaul",),
            counter_evidence_terms=tuple(
                (
                    kind,
                    ("repair",) if kind == CapitalizationSupportKind.DISTINCT_NEW_ASSET else terms,
                )
                for kind, terms in CapitalizationVocabulary().counter_evidence_terms
            ),
        )


@pytest.mark.parametrize("use_reclassification", [False, True])
def test_non_asset_reversal_or_reclassification_cannot_clear_asset_exposure(
    use_reclassification: bool,
) -> None:
    addition = _addition("addition-non-asset-clear", "Routine repair")
    asset_posting = _posting(
        "addition-non-asset-clear",
        "Asset debit",
        posting_id="asset-debit",
    )
    if use_reclassification:
        other_records = (
            _posting(
                "addition-non-asset-clear",
                "Expense reclassification",
                row=9,
                amount="-1250.00",
                posting_id="expense-reclassification",
                account_classification=AccountClassification.MAINTENANCE_EXPENSE,
                is_reclassification=True,
            ),
        )
        expected_counter_rows = {9}
    else:
        expense_posting = _posting(
            "addition-non-asset-clear",
            "Maintenance expense",
            row=8,
            posting_id="expense-posting",
            account_classification=AccountClassification.MAINTENANCE_EXPENSE,
        )
        other_records = (
            expense_posting,
            _posting(
                "addition-non-asset-clear",
                "Expense reversal",
                row=9,
                amount="-1250.00",
                posting_id="expense-reversal",
                account_classification=AccountClassification.MAINTENANCE_EXPENSE,
                reversal_of="expense-posting",
            ),
        )
        expected_counter_rows = {8, 9}

    outcome = _evaluate((addition, asset_posting, *other_records))[0]

    assert outcome.status == OutcomeStatus.REVIEW_NEEDED
    assert outcome.exposure_amount == Decimal("1250.00")
    reversal = _counter(
        outcome, CapitalizationSupportKind.REVERSAL_OR_RECLASSIFICATION
    )
    assert reversal.status == CounterTestStatus.UNRESOLVED
    assert {evidence.row for evidence in reversal.evidence_refs} == expected_counter_rows


def test_semantic_duplicates_merge_evidence_without_inflating_exposure() -> None:
    addition = _addition("addition-semantic-duplicate", "Equipment acquisition")
    posting = _posting("addition-semantic-duplicate", "Asset posting")
    invoice = _invoice("addition-semantic-duplicate", "Equipment invoice")
    asset = _asset("asset-one", "Distinct production equipment", distinct=True)
    duplicate_posting = replace(
        posting,
        record_id="duplicate-posting-record",
        evidence_refs=_evidence(12, "Asset posting duplicate source"),
    )
    duplicate_invoice = replace(
        invoice,
        record_id="duplicate-invoice-record",
        evidence_refs=_evidence(13, "Equipment invoice duplicate source"),
    )
    duplicate_asset = replace(
        asset,
        record_id="duplicate-asset-record",
        evidence_refs=_evidence(14, "Distinct production equipment duplicate source"),
    )

    outcome = _evaluate(
        (
            addition,
            posting,
            duplicate_posting,
            invoice,
            duplicate_invoice,
            asset,
            duplicate_asset,
            _support(
                "addition-semantic-duplicate",
                CapitalizationSupportKind.INVESTMENT_APPROVAL,
                row=15,
            ),
        )
    )[0]

    assert outcome.status == OutcomeStatus.DISMISSED
    assert outcome.exposure_amount == Decimal("1250.00")
    asset_signal = next(
        signal
        for signal in outcome.signals
        if signal.signal_type == CapitalizationSignalType.POSTED_TO_ASSET_ACCOUNT
    )
    assert {evidence.row for evidence in asset_signal.evidence_refs} == {2, 12}
    distinct = _counter(outcome, CapitalizationSupportKind.DISTINCT_NEW_ASSET)
    assert {evidence.row for evidence in distinct.evidence_refs} == {4, 14}
    reconciliation = outcome.calculation_steps[2]
    assert {evidence.row for evidence in reconciliation.evidence_refs} == {
        1,
        2,
        3,
        12,
        13,
    }
    assert reconciliation.expression == "asset=1250.00; gl=1250.00; invoice=1250.00"


def test_conflicting_asset_and_support_evidence_remains_unresolved() -> None:
    positive_asset = _asset("asset-one", "Production equipment", distinct=True)
    negative_asset = replace(
        positive_asset,
        record_id="asset-conflicting-record",
        distinct_new_asset=False,
        evidence_refs=_evidence(14, "not a distinct asset"),
    )
    approval = _support(
        "addition-conflict",
        CapitalizationSupportKind.INVESTMENT_APPROVAL,
        row=15,
    )
    approval_denial = replace(
        approval,
        record_id="support-conflicting-record",
        present=False,
        evidence_refs=_evidence(16, "approval not found"),
    )

    outcome = _evaluate(
        (
            _addition("addition-conflict", "Production equipment"),
            _posting("addition-conflict", "Asset posting"),
            positive_asset,
            negative_asset,
            approval,
            approval_denial,
        )
    )[0]

    assert outcome.status == OutcomeStatus.REVIEW_NEEDED
    distinct = _counter(outcome, CapitalizationSupportKind.DISTINCT_NEW_ASSET)
    investment = _counter(outcome, CapitalizationSupportKind.INVESTMENT_APPROVAL)
    assert distinct.status == CounterTestStatus.UNRESOLVED
    assert investment.status == CounterTestStatus.UNRESOLVED
    assert {evidence.row for evidence in distinct.evidence_refs} == {4, 14}
    assert {evidence.row for evidence in investment.evidence_refs} == {15, 16}


def test_absence_signals_require_evidence_of_a_documented_search() -> None:
    unresolved = _evaluate(
        (_addition("addition-unsearched", "Production equipment"),)
    )[0]
    assert not {
        CapitalizationSignalType.NO_DISTINCT_ASSET_OR_PROJECT_REFERENCE,
        CapitalizationSignalType.NO_INVESTMENT_APPROVAL,
        CapitalizationSignalType.NO_USEFUL_LIFE_OR_CAPACITY_IMPROVEMENT,
    } & _signal_types(unresolved)

    searched_records = (
        _addition("addition-searched", "Production equipment"),
        _support(
            "addition-searched",
            CapitalizationSupportKind.DISTINCT_NEW_ASSET,
            row=21,
            present=False,
        ),
        _support(
            "addition-searched",
            CapitalizationSupportKind.PROJECT_REFERENCE,
            row=22,
            present=False,
        ),
        _support(
            "addition-searched",
            CapitalizationSupportKind.INVESTMENT_APPROVAL,
            row=23,
            present=False,
        ),
        _support(
            "addition-searched",
            CapitalizationSupportKind.USEFUL_LIFE_EXTENSION,
            row=24,
            present=False,
        ),
        _support(
            "addition-searched",
            CapitalizationSupportKind.CAPACITY_OR_QUALITY_IMPROVEMENT,
            row=25,
            present=False,
        ),
    )
    searched = _evaluate(searched_records)[0]

    absence_signals = {
        signal.signal_type: {evidence.row for evidence in signal.evidence_refs}
        for signal in searched.signals
    }
    assert absence_signals[
        CapitalizationSignalType.NO_DISTINCT_ASSET_OR_PROJECT_REFERENCE
    ] == {21, 22}
    assert absence_signals[CapitalizationSignalType.NO_INVESTMENT_APPROVAL] == {23}
    assert absence_signals[
        CapitalizationSignalType.NO_USEFUL_LIFE_OR_CAPACITY_IMPROVEMENT
    ] == {24, 25}


def test_non_asset_transactions_without_asset_additions_emit_no_case() -> None:
    inventory = (
        _posting(
            "inventory-purchase",
            "Machine repair kit",
            account_classification=AccountClassification.OTHER,
        ),
        _invoice("inventory-purchase", "Machine repair kit"),
    )
    maintenance = (
        _posting(
            "maintenance-expense",
            "Routine maintenance",
            account_classification=AccountClassification.MAINTENANCE_EXPENSE,
        ),
        _invoice("maintenance-expense", "Routine maintenance"),
    )

    assert _evaluate(inventory) == ()
    assert _evaluate(maintenance) == ()
