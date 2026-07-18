"""LEGACY STRONG CONTROL: available behind the controls API, not production-integrated."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, TypeVar

from audit_compiler.controls.base import (
    CalculationStep,
    ControlContext,
    ControlOutcome,
    CounterTestResult,
    CounterTestStatus,
    OutcomeStatus,
    SupportingEvidence,
)
from audit_compiler.models import EvidenceRef
from audit_compiler.normalization import normalize_identifier


class AccountClassification(StrEnum):
    ASSET = "asset"
    MAINTENANCE_EXPENSE = "maintenance_expense"
    OTHER = "other"


class CapitalizationSupportKind(StrEnum):
    DISTINCT_NEW_ASSET = "distinct_new_asset"
    PROJECT_REFERENCE = "project_reference"
    INVESTMENT_APPROVAL = "investment_approval"
    SEPARABLE_MAJOR_COMPONENT = "separable_major_component"
    USEFUL_LIFE_EXTENSION = "useful_life_extension"
    CAPACITY_OR_QUALITY_IMPROVEMENT = "capacity_or_quality_improvement"
    REQUIRED_FOR_NEW_ASSET_OPERATION = "required_for_new_asset_operation"
    REVERSAL_OR_RECLASSIFICATION = "reversal_or_reclassification"


class CapitalizationSignalType(StrEnum):
    REPAIR_OR_MAINTENANCE_LANGUAGE = "repair_or_maintenance_language"
    REPLACEMENT_OVERHAUL_SERVICE_LANGUAGE = "replacement_overhaul_service_language"
    POSTED_TO_ASSET_ACCOUNT = "posted_to_asset_account"
    NO_DISTINCT_ASSET_OR_PROJECT_REFERENCE = "no_distinct_asset_or_project_reference"
    NO_INVESTMENT_APPROVAL = "no_investment_approval"
    NO_USEFUL_LIFE_OR_CAPACITY_IMPROVEMENT = "no_useful_life_or_capacity_improvement"
    MULTIPLE_REPAIR_LIKE_ADDITIONS = "multiple_repair_like_additions"


_DEFAULT_COUNTER_TERMS = (
    (CapitalizationSupportKind.DISTINCT_NEW_ASSET, ("new asset", "neue anlage")),
    (CapitalizationSupportKind.PROJECT_REFERENCE, ("project", "projekt")),
    (
        CapitalizationSupportKind.INVESTMENT_APPROVAL,
        ("investment approval", "investitionsfreigabe"),
    ),
    (
        CapitalizationSupportKind.SEPARABLE_MAJOR_COMPONENT,
        ("major component", "separable component", "wesentliche komponente"),
    ),
    (
        CapitalizationSupportKind.USEFUL_LIFE_EXTENSION,
        ("useful life extension", "verlängerung der nutzungsdauer"),
    ),
    (
        CapitalizationSupportKind.CAPACITY_OR_QUALITY_IMPROVEMENT,
        ("capacity increase", "quality improvement", "kapazitätserhöhung"),
    ),
    (
        CapitalizationSupportKind.REQUIRED_FOR_NEW_ASSET_OPERATION,
        ("bring into operation", "inbetriebnahme"),
    ),
    (
        CapitalizationSupportKind.REVERSAL_OR_RECLASSIFICATION,
        ("reversal", "reclassification", "storno", "umbuchung"),
    ),
)


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


@dataclass(frozen=True, slots=True)
class CapitalizationVocabulary:
    repair_maintenance_triggers: tuple[str, ...] = (
        "repair",
        "maintenance",
        "reparatur",
        "wartung",
        "instandhaltung",
    )
    replacement_overhaul_triggers: tuple[str, ...] = (
        "replacement",
        "overhaul",
        "servicing",
        "restoration",
        "austausch",
        "ersatz",
        "überholung",
        "restaurierung",
    )
    counter_evidence_terms: tuple[
        tuple[CapitalizationSupportKind, tuple[str, ...]], ...
    ] = _DEFAULT_COUNTER_TERMS

    def __post_init__(self) -> None:
        trigger_terms = (*self.repair_maintenance_triggers, *self.replacement_overhaul_triggers)
        if not trigger_terms or any(not term.strip() for term in trigger_terms):
            raise ValueError("trigger vocabulary must contain non-empty terms")
        kinds = [kind for kind, _ in self.counter_evidence_terms]
        if not all(isinstance(kind, CapitalizationSupportKind) for kind in kinds):
            raise TypeError("counter vocabulary keys must be CapitalizationSupportKind")
        if set(kinds) != set(CapitalizationSupportKind) or len(kinds) != len(set(kinds)):
            raise ValueError("counter vocabulary must configure every support kind exactly once")
        counter_terms = tuple(
            term for _, terms in self.counter_evidence_terms for term in terms
        )
        if any(not term.strip() for term in counter_terms):
            raise ValueError("counter-evidence vocabulary terms must not be empty")
        normalized_triggers = {_normalize_text(term) for term in trigger_terms}
        normalized_counters = {_normalize_text(term) for term in counter_terms}
        if normalized_triggers & normalized_counters:
            raise ValueError("trigger and counter-evidence vocabularies must remain separate")

    def counter_terms_for(self, kind: CapitalizationSupportKind) -> tuple[str, ...]:
        return dict(self.counter_evidence_terms)[kind]


_DEFAULT_WEIGHTS = tuple((signal, Decimal("1")) for signal in CapitalizationSignalType)


@dataclass(frozen=True, slots=True)
class CapitalizationParameters:
    vocabulary: CapitalizationVocabulary = CapitalizationVocabulary()
    cluster_window_days: int = 30
    cluster_minimum_count: int = 2
    severity_weights: tuple[
        tuple[CapitalizationSignalType, Decimal], ...
    ] = _DEFAULT_WEIGHTS

    def __post_init__(self) -> None:
        if isinstance(self.cluster_window_days, bool) or not isinstance(
            self.cluster_window_days, int
        ):
            raise TypeError("cluster_window_days must be an integer")
        if self.cluster_window_days < 0:
            raise ValueError("cluster_window_days must not be negative")
        if isinstance(self.cluster_minimum_count, bool) or not isinstance(
            self.cluster_minimum_count, int
        ):
            raise TypeError("cluster_minimum_count must be an integer")
        if self.cluster_minimum_count < 2:
            raise ValueError("cluster_minimum_count must be at least two")
        signals = [signal for signal, _ in self.severity_weights]
        if len(signals) != len(set(signals)) or set(signals) != set(
            CapitalizationSignalType
        ):
            raise ValueError("severity_weights must configure every signal exactly once")
        for signal, weight in self.severity_weights:
            if not isinstance(signal, CapitalizationSignalType):
                raise TypeError("severity-weight keys must be CapitalizationSignalType")
            _validate_decimal(f"weight {signal.value}", weight)

    def weight_for(self, signal: CapitalizationSignalType) -> Decimal:
        return dict(self.severity_weights)[signal]

    def as_items(self) -> tuple[tuple[str, str], ...]:
        weights = tuple(
            (f"weight.{signal.value}", str(weight))
            for signal, weight in sorted(
                self.severity_weights, key=lambda item: item[0].value
            )
        )
        counter_vocabulary = tuple(
            (f"counter_terms.{kind.value}", "|".join(terms))
            for kind, terms in sorted(
                self.vocabulary.counter_evidence_terms,
                key=lambda item: item[0].value,
            )
        )
        return (
            ("cluster_window_days", str(self.cluster_window_days)),
            ("cluster_minimum_count", str(self.cluster_minimum_count)),
            (
                "repair_maintenance_triggers",
                "|".join(self.vocabulary.repair_maintenance_triggers),
            ),
            (
                "replacement_overhaul_triggers",
                "|".join(self.vocabulary.replacement_overhaul_triggers),
            ),
            *counter_vocabulary,
            *weights,
        )


def _validate_identifier(name: str, value: object, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _validate_evidence(evidence_refs: tuple[EvidenceRef, ...]) -> None:
    if not evidence_refs:
        raise ValueError("every normalized input requires at least one EvidenceRef")
    if not all(isinstance(evidence, EvidenceRef) for evidence in evidence_refs):
        raise TypeError("evidence_refs must contain only EvidenceRefs")


def _validate_date(name: str, value: object) -> None:
    if type(value) is not date:
        raise TypeError(f"{name} must be a date")


def _validate_decimal(name: str, value: object, *, allow_negative: bool = False) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if not allow_negative and value < 0:
        raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class FixedAssetAdditionRecord:
    record_id: str
    addition_id: str
    asset_id: str
    vendor_id: str | None
    addition_date: date
    net_amount: Decimal
    description: str
    category: str | None
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        _validate_identifier("record_id", self.record_id)
        _validate_identifier("addition_id", self.addition_id)
        _validate_identifier("asset_id", self.asset_id)
        _validate_identifier("vendor_id", self.vendor_id, optional=True)
        _validate_date("addition_date", self.addition_date)
        _validate_decimal("net_amount", self.net_amount)
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")
        _validate_identifier("category", self.category, optional=True)
        _validate_evidence(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class GeneralLedgerPostingRecord:
    record_id: str
    posting_id: str
    addition_id: str
    account_id: str
    account_classification: AccountClassification
    posting_date: date
    amount: Decimal
    description: str
    evidence_refs: tuple[EvidenceRef, ...]
    reversal_of_posting_id: str | None = None
    is_reclassification: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("record_id", self.record_id),
            ("posting_id", self.posting_id),
            ("addition_id", self.addition_id),
            ("account_id", self.account_id),
        ):
            _validate_identifier(name, value)
        _validate_identifier(
            "reversal_of_posting_id", self.reversal_of_posting_id, optional=True
        )
        _validate_date("posting_date", self.posting_date)
        _validate_decimal("amount", self.amount, allow_negative=True)
        if not isinstance(self.account_classification, AccountClassification):
            raise TypeError("account_classification must be AccountClassification")
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")
        if not isinstance(self.is_reclassification, bool):
            raise TypeError("is_reclassification must be boolean")
        if self.reversal_of_posting_id is not None and self.amount >= 0:
            raise ValueError("a reversal posting must have a negative amount")
        if self.is_reclassification and self.amount >= 0:
            raise ValueError("a reclassification away from an asset must be negative")
        _validate_evidence(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class CapitalizationInvoiceRecord:
    record_id: str
    invoice_id: str
    addition_id: str
    invoice_date: date
    net_amount: Decimal | None
    description: str
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("record_id", self.record_id),
            ("invoice_id", self.invoice_id),
            ("addition_id", self.addition_id),
        ):
            _validate_identifier(name, value)
        _validate_date("invoice_date", self.invoice_date)
        if self.net_amount is not None:
            _validate_decimal("net_amount", self.net_amount)
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")
        _validate_evidence(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class AssetDescriptionRecord:
    record_id: str
    asset_id: str
    description: str
    category: str | None
    distinct_new_asset: bool | None
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        _validate_identifier("record_id", self.record_id)
        _validate_identifier("asset_id", self.asset_id)
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")
        _validate_identifier("category", self.category, optional=True)
        if self.distinct_new_asset is not None and not isinstance(
            self.distinct_new_asset, bool
        ):
            raise TypeError("distinct_new_asset must be boolean or None")
        _validate_evidence(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class CapitalizationSupportRecord:
    record_id: str
    addition_id: str
    kind: CapitalizationSupportKind
    present: bool
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        _validate_identifier("record_id", self.record_id)
        _validate_identifier("addition_id", self.addition_id)
        if not isinstance(self.kind, CapitalizationSupportKind):
            raise TypeError("kind must be CapitalizationSupportKind")
        if not isinstance(self.present, bool):
            raise TypeError("present must be boolean")
        _validate_evidence(self.evidence_refs)


CapitalizationRecord = (
    FixedAssetAdditionRecord
    | GeneralLedgerPostingRecord
    | CapitalizationInvoiceRecord
    | AssetDescriptionRecord
    | CapitalizationSupportRecord
)
DescriptionRecord = (
    FixedAssetAdditionRecord
    | GeneralLedgerPostingRecord
    | CapitalizationInvoiceRecord
    | AssetDescriptionRecord
)


@dataclass(frozen=True, slots=True)
class CapitalizationSignal:
    signal_type: CapitalizationSignalType
    weight: Decimal
    description: str
    evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        _validate_decimal("signal weight", self.weight)
        _validate_evidence(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class CapitalizationOutcome(ControlOutcome):
    addition_id: str
    asset_id: str
    capitalized_net_amount: Decimal
    severity_score: Decimal
    matched_trigger_terms: tuple[str, ...]
    signals: tuple[CapitalizationSignal, ...]


RecordT = TypeVar("RecordT")


class _HasEvidence(Protocol):
    evidence_refs: tuple[EvidenceRef, ...]


def _deduplicate(records: tuple[RecordT, ...]) -> tuple[RecordT, ...]:
    by_id: dict[tuple[type, str], RecordT] = {}
    for record in records:
        key = (type(record), record.record_id)
        existing = by_id.get(key)
        if existing is not None and existing != record:
            raise ValueError(f"conflicting duplicate record_id: {record.record_id}")
        by_id[key] = record
    return tuple(
        by_id[key]
        for key in sorted(by_id, key=lambda item: (item[0].__name__, item[1]))
    )


def _deduplicate_business_records(
    records: tuple[RecordT, ...],
    business_key: Callable[[RecordT], object],
    fingerprint: Callable[[RecordT], object],
    label: str,
) -> tuple[RecordT, ...]:
    by_key: dict[object, RecordT] = {}
    for record in records:
        key = business_key(record)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = record
            continue
        if fingerprint(existing) != fingerprint(record):
            raise ValueError(f"conflicting duplicate {label}: {key}")
        by_key[key] = replace(
            existing,
            evidence_refs=_merge_evidence(
                existing.evidence_refs,
                record.evidence_refs,
            ),
        )
    return tuple(by_key[key] for key in sorted(by_key, key=repr))


def _merge_evidence(*groups: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
    result: list[EvidenceRef] = []
    seen = set()
    for group in groups:
        for evidence in group:
            if evidence.evidence_id in seen:
                continue
            seen.add(evidence.evidence_id)
            result.append(evidence)
    return tuple(result)


def _record_evidence(records: tuple[_HasEvidence, ...]) -> tuple[EvidenceRef, ...]:
    return _merge_evidence(*(record.evidence_refs for record in records))


def _normalized_optional_identifier(value: str | None) -> str | None:
    return normalize_identifier(value) if value is not None else None


def _deduplicate_additions(
    records: tuple[FixedAssetAdditionRecord, ...],
) -> tuple[FixedAssetAdditionRecord, ...]:
    return _deduplicate_business_records(
        records,
        business_key=lambda record: normalize_identifier(record.addition_id),
        fingerprint=lambda record: (
            normalize_identifier(record.addition_id),
            normalize_identifier(record.asset_id),
            _normalized_optional_identifier(record.vendor_id),
            record.addition_date,
            record.net_amount,
            _normalize_text(record.description),
            _normalized_optional_identifier(record.category),
        ),
        label="addition_id",
    )


def _deduplicate_postings(
    records: tuple[GeneralLedgerPostingRecord, ...],
) -> tuple[GeneralLedgerPostingRecord, ...]:
    return _deduplicate_business_records(
        records,
        business_key=lambda record: normalize_identifier(record.posting_id),
        fingerprint=lambda record: (
            normalize_identifier(record.posting_id),
            normalize_identifier(record.addition_id),
            normalize_identifier(record.account_id),
            record.account_classification,
            record.posting_date,
            record.amount,
            _normalize_text(record.description),
            _normalized_optional_identifier(record.reversal_of_posting_id),
            record.is_reclassification,
        ),
        label="posting_id",
    )


def _deduplicate_invoices(
    records: tuple[CapitalizationInvoiceRecord, ...],
) -> tuple[CapitalizationInvoiceRecord, ...]:
    return _deduplicate_business_records(
        records,
        business_key=lambda record: normalize_identifier(record.invoice_id),
        fingerprint=lambda record: (
            normalize_identifier(record.invoice_id),
            normalize_identifier(record.addition_id),
            record.invoice_date,
            record.net_amount,
            _normalize_text(record.description),
        ),
        label="invoice_id",
    )


def _deduplicate_asset_descriptions(
    records: tuple[AssetDescriptionRecord, ...],
) -> tuple[AssetDescriptionRecord, ...]:
    return _deduplicate_business_records(
        records,
        business_key=lambda record: (
            normalize_identifier(record.asset_id),
            _normalize_text(record.description),
            _normalized_optional_identifier(record.category),
            record.distinct_new_asset,
        ),
        fingerprint=lambda record: (
            normalize_identifier(record.asset_id),
            _normalize_text(record.description),
            _normalized_optional_identifier(record.category),
            record.distinct_new_asset,
        ),
        label="asset description",
    )


def _deduplicate_support(
    records: tuple[CapitalizationSupportRecord, ...],
) -> tuple[CapitalizationSupportRecord, ...]:
    return _deduplicate_business_records(
        records,
        business_key=lambda record: (
            normalize_identifier(record.addition_id),
            record.kind.value,
            record.present,
        ),
        fingerprint=lambda record: (
            normalize_identifier(record.addition_id),
            record.kind,
            record.present,
        ),
        label="support record",
    )


def _matching_terms(text: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    normalized = _normalize_text(text)
    matches = {
        term
        for term in terms
        if re.search(rf"(?<!\w){re.escape(_normalize_text(term))}(?!\w)", normalized)
    }
    return tuple(sorted(matches, key=lambda term: _normalize_text(term)))


def _record_text(record: DescriptionRecord) -> str:
    if isinstance(record, (FixedAssetAdditionRecord, AssetDescriptionRecord)):
        return " ".join(
            part for part in (record.description, record.category) if part is not None
        )
    return record.description


def _support_test(
    *,
    kind: CapitalizationSupportKind,
    support: tuple[CapitalizationSupportRecord, ...],
    text_records: tuple[DescriptionRecord, ...],
    vocabulary: CapitalizationVocabulary,
) -> CounterTestResult:
    records = tuple(record for record in support if record.kind == kind)
    present_records = tuple(record for record in records if record.present)
    absent_records = tuple(record for record in records if not record.present)
    if present_records and absent_records:
        evidence = _record_evidence(records)
        status = CounterTestStatus.UNRESOLVED
        description = f"conflicting {kind.value} evidence was supplied"
    elif present_records:
        evidence = _record_evidence(present_records)
        status = CounterTestStatus.ACCOUNTED_FOR
        description = f"{kind.value} evidence is present"
    elif records:
        evidence = _record_evidence(records)
        status = CounterTestStatus.NOT_FOUND
        description = f"a documented search found no {kind.value} evidence"
    else:
        hinted = tuple(
            record
            for record in text_records
            if _matching_terms(_record_text(record), vocabulary.counter_terms_for(kind))
        )
        evidence = _record_evidence(hinted)
        status = CounterTestStatus.UNRESOLVED
        description = (
            f"description suggests {kind.value}, but supporting evidence is required"
            if hinted
            else f"no {kind.value} evidence or documented search was supplied"
        )
    return CounterTestResult(
        name=kind.value,
        status=status,
        description=description,
        evidence_refs=evidence,
    )


class CapitalizationControl:
    control_id = "capital_expenditure_classification"
    version = "1.0.0"

    def evaluate(
        self,
        context: ControlContext[CapitalizationRecord, CapitalizationParameters],
    ) -> tuple[CapitalizationOutcome, ...]:
        if not isinstance(context.parameters, CapitalizationParameters):
            raise TypeError("CapitalizationControl requires CapitalizationParameters")
        allowed = (
            FixedAssetAdditionRecord,
            GeneralLedgerPostingRecord,
            CapitalizationInvoiceRecord,
            AssetDescriptionRecord,
            CapitalizationSupportRecord,
        )
        if not all(isinstance(record, allowed) for record in context.records):
            raise TypeError("CapitalizationControl received an unsupported input record")
        records = _deduplicate(context.records)
        additions = _deduplicate_additions(
            tuple(record for record in records if isinstance(record, FixedAssetAdditionRecord))
        )
        postings = _deduplicate_postings(
            tuple(record for record in records if isinstance(record, GeneralLedgerPostingRecord))
        )
        invoices = _deduplicate_invoices(
            tuple(record for record in records if isinstance(record, CapitalizationInvoiceRecord))
        )
        assets = _deduplicate_asset_descriptions(
            tuple(record for record in records if isinstance(record, AssetDescriptionRecord))
        )
        support = _deduplicate_support(
            tuple(record for record in records if isinstance(record, CapitalizationSupportRecord))
        )

        repair_like: dict[str, bool] = {}
        for addition in additions:
            addition_id = normalize_identifier(addition.addition_id)
            linked_text = self._text_records(addition, postings, invoices, assets)
            all_trigger_terms = (
                *context.parameters.vocabulary.repair_maintenance_triggers,
                *context.parameters.vocabulary.replacement_overhaul_triggers,
            )
            repair_like[addition_id] = any(
                _matching_terms(_record_text(record), all_trigger_terms)
                for record in linked_text
            )

        outcomes = tuple(
            self._evaluate_addition(
                addition=addition,
                additions=additions,
                postings=postings,
                invoices=invoices,
                assets=assets,
                support=support,
                repair_like=repair_like,
                parameters=context.parameters,
            )
            for addition in sorted(
                additions, key=lambda record: normalize_identifier(record.addition_id)
            )
        )
        return outcomes

    @staticmethod
    def _text_records(
        addition: FixedAssetAdditionRecord,
        postings: tuple[GeneralLedgerPostingRecord, ...],
        invoices: tuple[CapitalizationInvoiceRecord, ...],
        assets: tuple[AssetDescriptionRecord, ...],
    ) -> tuple[DescriptionRecord, ...]:
        addition_id = normalize_identifier(addition.addition_id)
        asset_id = normalize_identifier(addition.asset_id)
        return (
            addition,
            *(
                posting
                for posting in postings
                if normalize_identifier(posting.addition_id) == addition_id
            ),
            *(
                invoice
                for invoice in invoices
                if normalize_identifier(invoice.addition_id) == addition_id
            ),
            *(
                asset for asset in assets if normalize_identifier(asset.asset_id) == asset_id
            ),
        )

    def _evaluate_addition(
        self,
        *,
        addition: FixedAssetAdditionRecord,
        additions: tuple[FixedAssetAdditionRecord, ...],
        postings: tuple[GeneralLedgerPostingRecord, ...],
        invoices: tuple[CapitalizationInvoiceRecord, ...],
        assets: tuple[AssetDescriptionRecord, ...],
        support: tuple[CapitalizationSupportRecord, ...],
        repair_like: dict[str, bool],
        parameters: CapitalizationParameters,
    ) -> CapitalizationOutcome:
        addition_id = normalize_identifier(addition.addition_id)
        asset_id = normalize_identifier(addition.asset_id)
        vendor_id = (
            normalize_identifier(addition.vendor_id) if addition.vendor_id is not None else ""
        )
        linked_postings = tuple(
            posting
            for posting in postings
            if normalize_identifier(posting.addition_id) == addition_id
        )
        linked_invoices = tuple(
            invoice
            for invoice in invoices
            if normalize_identifier(invoice.addition_id) == addition_id
        )
        linked_assets = tuple(
            asset for asset in assets if normalize_identifier(asset.asset_id) == asset_id
        )
        linked_support = tuple(
            record
            for record in support
            if normalize_identifier(record.addition_id) == addition_id
        )
        text_records = self._text_records(addition, postings, invoices, assets)
        repair_terms_by_record = tuple(
            (
                record,
                _matching_terms(
                    _record_text(record),
                    parameters.vocabulary.repair_maintenance_triggers,
                ),
            )
            for record in text_records
        )
        replacement_terms_by_record = tuple(
            (
                record,
                _matching_terms(
                    _record_text(record),
                    parameters.vocabulary.replacement_overhaul_triggers,
                ),
            )
            for record in text_records
        )
        repair_records = tuple(record for record, terms in repair_terms_by_record if terms)
        replacement_records = tuple(
            record for record, terms in replacement_terms_by_record if terms
        )
        matched_terms = tuple(
            sorted(
                {
                    term
                    for _, terms in (*repair_terms_by_record, *replacement_terms_by_record)
                    for term in terms
                },
                key=_normalize_text,
            )
        )

        counter_tests = {
            kind: _support_test(
                kind=kind,
                support=linked_support,
                text_records=text_records,
                vocabulary=parameters.vocabulary,
            )
            for kind in CapitalizationSupportKind
        }
        distinct_asset_records = tuple(
            record for record in linked_assets if record.distinct_new_asset is not None
        )
        positive_asset_records = tuple(
            record for record in distinct_asset_records if record.distinct_new_asset
        )
        negative_asset_records = tuple(
            record for record in distinct_asset_records if not record.distinct_new_asset
        )
        if positive_asset_records and negative_asset_records:
            counter_tests[CapitalizationSupportKind.DISTINCT_NEW_ASSET] = CounterTestResult(
                name=CapitalizationSupportKind.DISTINCT_NEW_ASSET.value,
                status=CounterTestStatus.UNRESOLVED,
                description="asset records conflict on whether this is a distinct new asset",
                evidence_refs=_record_evidence(distinct_asset_records),
            )
        elif positive_asset_records:
            counter_tests[CapitalizationSupportKind.DISTINCT_NEW_ASSET] = CounterTestResult(
                name=CapitalizationSupportKind.DISTINCT_NEW_ASSET.value,
                status=CounterTestStatus.ACCOUNTED_FOR,
                description="asset records identify a distinct new asset",
                evidence_refs=_record_evidence(positive_asset_records),
            )
        elif distinct_asset_records:
            counter_tests[CapitalizationSupportKind.DISTINCT_NEW_ASSET] = CounterTestResult(
                name=CapitalizationSupportKind.DISTINCT_NEW_ASSET.value,
                status=CounterTestStatus.NOT_FOUND,
                description="asset records do not identify a distinct new asset",
                evidence_refs=_record_evidence(distinct_asset_records),
            )

        posting_by_id = {
            normalize_identifier(posting.posting_id): posting for posting in linked_postings
        }
        reversal_records: list[GeneralLedgerPostingRecord] = []
        unresolved_reversal_records: list[GeneralLedgerPostingRecord] = []
        for posting in linked_postings:
            target = (
                posting_by_id.get(normalize_identifier(posting.reversal_of_posting_id))
                if posting.reversal_of_posting_id is not None
                else None
            )
            if (
                posting.is_reclassification
                and posting.account_classification == AccountClassification.ASSET
                and posting.posting_date >= addition.addition_date
            ):
                reversal_records.extend(
                    record
                    for record in linked_postings
                    if record.account_classification == AccountClassification.ASSET
                    and record.amount > 0
                )
                reversal_records.append(posting)
            elif posting.is_reclassification:
                unresolved_reversal_records.append(posting)
            elif (
                target is not None
                and posting.amount == -target.amount
                and target.posting_date >= addition.addition_date
                and target.posting_date <= posting.posting_date
                and target.account_classification == AccountClassification.ASSET
                and posting.account_classification == AccountClassification.ASSET
            ):
                reversal_records.extend((target, posting))
            elif posting.reversal_of_posting_id is not None:
                if target is not None:
                    unresolved_reversal_records.append(target)
                unresolved_reversal_records.append(posting)
        if unresolved_reversal_records:
            counter_tests[
                CapitalizationSupportKind.REVERSAL_OR_RECLASSIFICATION
            ] = CounterTestResult(
                name=CapitalizationSupportKind.REVERSAL_OR_RECLASSIFICATION.value,
                status=CounterTestStatus.UNRESOLVED,
                description=(
                    "a reversal or reclassification could not be matched to an "
                    "asset posting deterministically"
                ),
                evidence_refs=_record_evidence(
                    tuple((*reversal_records, *unresolved_reversal_records))
                ),
            )
        elif reversal_records:
            counter_tests[
                CapitalizationSupportKind.REVERSAL_OR_RECLASSIFICATION
            ] = CounterTestResult(
                name=CapitalizationSupportKind.REVERSAL_OR_RECLASSIFICATION.value,
                status=CounterTestStatus.ACCOUNTED_FOR,
                description="a deterministic reversal or reclassification is present",
                evidence_refs=_record_evidence(tuple(reversal_records)),
            )

        signals: list[CapitalizationSignal] = []

        def add_signal(
            signal_type: CapitalizationSignalType,
            description: str,
            evidence_refs: tuple[EvidenceRef, ...],
        ) -> None:
            signals.append(
                CapitalizationSignal(
                    signal_type=signal_type,
                    weight=parameters.weight_for(signal_type),
                    description=description,
                    evidence_refs=evidence_refs,
                )
            )

        if repair_records:
            add_signal(
                CapitalizationSignalType.REPAIR_OR_MAINTENANCE_LANGUAGE,
                "repair or maintenance trigger language appears in linked descriptions",
                _record_evidence(repair_records),
            )
        if replacement_records:
            add_signal(
                CapitalizationSignalType.REPLACEMENT_OVERHAUL_SERVICE_LANGUAGE,
                "replacement, overhaul, servicing, or restoration language appears",
                _record_evidence(replacement_records),
            )
        asset_postings = tuple(
            posting
            for posting in linked_postings
            if posting.account_classification == AccountClassification.ASSET
            and posting.amount > 0
        )
        if asset_postings:
            add_signal(
                CapitalizationSignalType.POSTED_TO_ASSET_ACCOUNT,
                "linked general-ledger postings debit an asset account",
                _record_evidence(asset_postings),
            )

        distinct_test = counter_tests[CapitalizationSupportKind.DISTINCT_NEW_ASSET]
        project_test = counter_tests[CapitalizationSupportKind.PROJECT_REFERENCE]
        if all(
            test.status == CounterTestStatus.NOT_FOUND
            for test in (distinct_test, project_test)
        ):
            negative_evidence = _merge_evidence(
                distinct_test.evidence_refs, project_test.evidence_refs
            )
            add_signal(
                CapitalizationSignalType.NO_DISTINCT_ASSET_OR_PROJECT_REFERENCE,
                "no supported distinct asset or project reference was supplied",
                negative_evidence or addition.evidence_refs,
            )
        investment_test = counter_tests[CapitalizationSupportKind.INVESTMENT_APPROVAL]
        if investment_test.status == CounterTestStatus.NOT_FOUND:
            add_signal(
                CapitalizationSignalType.NO_INVESTMENT_APPROVAL,
                "no supported investment approval was supplied",
                investment_test.evidence_refs or addition.evidence_refs,
            )
        useful_test = counter_tests[CapitalizationSupportKind.USEFUL_LIFE_EXTENSION]
        capacity_test = counter_tests[
            CapitalizationSupportKind.CAPACITY_OR_QUALITY_IMPROVEMENT
        ]
        if all(
            test.status == CounterTestStatus.NOT_FOUND
            for test in (useful_test, capacity_test)
        ):
            add_signal(
                CapitalizationSignalType.NO_USEFUL_LIFE_OR_CAPACITY_IMPROVEMENT,
                "no supported useful-life extension or capacity improvement was supplied",
                _merge_evidence(useful_test.evidence_refs, capacity_test.evidence_refs)
                or addition.evidence_refs,
            )

        cluster = tuple(
            candidate
            for candidate in additions
            if repair_like[normalize_identifier(candidate.addition_id)]
            and normalize_identifier(candidate.asset_id) == asset_id
            and (
                normalize_identifier(candidate.vendor_id)
                if candidate.vendor_id is not None
                else ""
            )
            == vendor_id
            and abs((candidate.addition_date - addition.addition_date).days)
            <= parameters.cluster_window_days
        )
        if len(cluster) >= parameters.cluster_minimum_count:
            add_signal(
                CapitalizationSignalType.MULTIPLE_REPAIR_LIKE_ADDITIONS,
                "multiple repair-like additions cluster around the same asset and vendor",
                _record_evidence(
                    tuple(sorted(cluster, key=lambda record: record.addition_id))
                ),
            )

        signals_tuple = tuple(
            sorted(signals, key=lambda signal: (signal.signal_type.value, signal.description))
        )
        severity_score = sum(
            (signal.weight for signal in signals_tuple), start=Decimal("0")
        )
        reversal_test = counter_tests[
            CapitalizationSupportKind.REVERSAL_OR_RECLASSIFICATION
        ]
        resolved_reversal_records = tuple(dict.fromkeys(reversal_records))
        reversal_adjustment = sum(
            (
                posting.amount
                for posting in resolved_reversal_records
                if posting.amount < 0
            ),
            start=Decimal("0"),
        )
        remaining_capitalized = addition.net_amount + reversal_adjustment
        capitalized_net = max(Decimal("0"), remaining_capitalized)

        valid_new_asset = (
            distinct_test.status == CounterTestStatus.ACCOUNTED_FOR
            and any(
                test.status == CounterTestStatus.ACCOUNTED_FOR
                for test in (project_test, investment_test)
            )
        )
        component_test = counter_tests[
            CapitalizationSupportKind.SEPARABLE_MAJOR_COMPONENT
        ]
        valid_component = (
            component_test.status == CounterTestStatus.ACCOUNTED_FOR
            and any(
                test.status == CounterTestStatus.ACCOUNTED_FOR
                for test in (useful_test, capacity_test)
            )
        )
        required_operation_test = counter_tests[
            CapitalizationSupportKind.REQUIRED_FOR_NEW_ASSET_OPERATION
        ]
        valid_operation_cost = (
            required_operation_test.status == CounterTestStatus.ACCOUNTED_FOR
            and any(
                test.status == CounterTestStatus.ACCOUNTED_FOR
                for test in (distinct_test, project_test)
            )
        )
        material_counter_tests = (
            distinct_test,
            project_test,
            investment_test,
            component_test,
            useful_test,
            capacity_test,
            required_operation_test,
        )
        uncertainty = tuple(
            sorted(
                {
                    test.description
                    for test in material_counter_tests
                    if test.status == CounterTestStatus.UNRESOLVED
                }
            )
        )
        if unresolved_reversal_records:
            status = OutcomeStatus.REVIEW_NEEDED
            uncertainty = tuple(
                sorted(
                    {
                        *uncertainty,
                        reversal_test.description,
                        "capitalization classification requires accounting judgement; "
                        "description matching alone is not proof of misstatement",
                    }
                )
            )
        elif (
            reversal_test.status == CounterTestStatus.ACCOUNTED_FOR
            and remaining_capitalized == Decimal("0")
        ):
            status = OutcomeStatus.DISMISSED
        elif valid_new_asset or valid_component or valid_operation_cost:
            status = OutcomeStatus.DISMISSED
        else:
            status = OutcomeStatus.REVIEW_NEEDED
            partial_reversal_uncertainty = (
                {
                    "a reversal or reclassification exists but does not clear the "
                    "entire capitalized net amount"
                }
                if reversal_test.status == CounterTestStatus.ACCOUNTED_FOR
                else set()
            )
            uncertainty = tuple(
                sorted(
                    {
                        *uncertainty,
                        *partial_reversal_uncertainty,
                        "capitalization classification requires accounting judgement; "
                        "description matching alone is not proof of misstatement",
                    }
                )
            )

        addition_evidence = addition.evidence_refs
        gl_evidence = _record_evidence(linked_postings)
        invoice_evidence = _record_evidence(linked_invoices)
        calculation_evidence = _merge_evidence(
            addition_evidence, gl_evidence, invoice_evidence
        )
        reversal_calculation_evidence = _merge_evidence(
            addition_evidence,
            _record_evidence(resolved_reversal_records),
        )
        gl_total = sum(
            (posting.amount for posting in linked_postings), start=Decimal("0")
        )
        invoice_total = sum(
            (
                invoice.net_amount
                for invoice in linked_invoices
                if invoice.net_amount is not None
            ),
            start=Decimal("0"),
        )
        calculations = (
            CalculationStep(
                sequence=1,
                label="authoritative capitalized net amount",
                expression=f"asset addition net amount = {addition.net_amount}",
                result=str(addition.net_amount),
                evidence_refs=addition_evidence,
            ),
            CalculationStep(
                sequence=2,
                label="reversal adjustment",
                expression=(
                    f"max(0, {addition.net_amount} + ({reversal_adjustment}))"
                ),
                result=str(capitalized_net),
                evidence_refs=reversal_calculation_evidence,
            ),
            CalculationStep(
                sequence=3,
                label="representation reconciliation",
                expression=(
                    f"asset={addition.net_amount}; "
                    f"gl={gl_total}; invoice={invoice_total}"
                ),
                result="representations_not_added_to_exposure",
                evidence_refs=calculation_evidence,
            ),
            CalculationStep(
                sequence=4,
                label="severity score",
                expression=" + ".join(str(signal.weight) for signal in signals_tuple) or "0",
                result=str(severity_score),
                evidence_refs=_merge_evidence(
                    *(signal.evidence_refs for signal in signals_tuple)
                )
                or addition_evidence,
            ),
        )
        counter_tuple = tuple(
            counter_tests[kind] for kind in CapitalizationSupportKind
        )
        supporting_outputs = tuple(
            SupportingEvidence(
                role=signal.signal_type.value,
                description=signal.description,
                evidence_refs=signal.evidence_refs,
            )
            for signal in signals_tuple
        ) or (
            SupportingEvidence(
                role="classification_input",
                description="fixed-asset addition evaluated by the control",
                evidence_refs=addition_evidence,
            ),
        )
        all_evidence = _merge_evidence(
            addition_evidence,
            *(signal.evidence_refs for signal in signals_tuple),
            *(counter.evidence_refs for counter in counter_tuple),
        )
        return CapitalizationOutcome(
            control_id=self.control_id,
            control_version=self.version,
            status=status,
            group_key=(("addition_id", addition_id), ("asset_id", asset_id)),
            rule_parameters=parameters.as_items(),
            exposure_amount=capitalized_net,
            supporting_evidence=supporting_outputs,
            counter_tests=counter_tuple,
            uncertainty=uncertainty,
            calculation_steps=calculations,
            evidence_refs=all_evidence,
            addition_id=addition_id,
            asset_id=asset_id,
            capitalized_net_amount=capitalized_net,
            severity_score=severity_score,
            matched_trigger_terms=matched_terms,
            signals=signals_tuple,
        )
