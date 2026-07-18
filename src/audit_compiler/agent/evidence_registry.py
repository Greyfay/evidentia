"""Stable, resolvable evidence identifiers for the investigation agent.

Every evidence pointer a tool surfaces is recorded here under a deterministic id derived
from its source coordinates. The id is what the LLM is allowed to cite; ids that are not in
the registry are rejected. This is how "no number without a source" and "the model may only
reference existing evidence ids" are enforced mechanically.
"""

from __future__ import annotations

import hashlib

from audit_compiler.models import EvidenceRef


class EvidenceRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, dict] = {}

    @staticmethod
    def _key(ref: EvidenceRef) -> str:
        locator = (
            f"{ref.source_path}|r{ref.row}|s{ref.sheet}|c{ref.cell}|p{ref.page}|{ref.raw_value}"
        )
        return "ev_" + hashlib.sha256(locator.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _serialize(evidence_id: str, ref: EvidenceRef) -> dict:
        return {
            "evidence_id": evidence_id,
            "source_path": ref.source_path,
            "source_type": ref.source_type.value,
            "locator": {
                "row": ref.row,
                "sheet": ref.sheet,
                "cell": ref.cell,
                "page": ref.page,
                "passage": ref.passage,
            },
            "raw_value": ref.raw_value,
            "normalized_value": ref.normalized_value,
            "file_sha256": ref.file_sha256,
        }

    def record(self, ref: EvidenceRef) -> str:
        """Register an evidence pointer and return its deterministic id."""

        evidence_id = self._key(ref)
        self._by_id.setdefault(evidence_id, self._serialize(evidence_id, ref))
        return evidence_id

    def resolve(self, evidence_id: str) -> dict | None:
        return self._by_id.get(evidence_id)

    def contains(self, evidence_id: str) -> bool:
        return evidence_id in self._by_id

    def validate(self, evidence_ids: object) -> None:
        """Raise if any id is not a recorded evidence pointer."""

        if not isinstance(evidence_ids, (list, tuple, set)):
            raise TypeError("evidence_ids must be a collection")
        unknown = [e for e in evidence_ids if e not in self._by_id]
        if unknown:
            raise ValueError(f"unknown evidence ids (not from any source): {unknown}")

    @property
    def all(self) -> dict[str, dict]:
        return dict(self._by_id)
