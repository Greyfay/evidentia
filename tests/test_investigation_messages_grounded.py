"""Tests for grounded answers to auditor questions.

``POST /investigations/{id}/messages`` records the question and produces an ``assistant_reply``
that is derived strictly from the investigation's real state — it never invents evidence ids,
and with no LLM configured it still returns a non-empty, state-derived answer.
"""

from __future__ import annotations

import importlib
import io
import zipfile
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from audit_compiler.agent import store as store_module
from audit_compiler.agent.answers import build_answer
from audit_compiler.agent.models import (
    Hypothesis,
    HypothesisCategory,
    HypothesisStatus,
    Investigation,
    InvestigationStatus,
    VerdictRecommendation,
)
from audit_compiler.agent.planner import DeterministicPlanner
from audit_compiler.api.app import app

app_module = importlib.import_module("audit_compiler.api.app")
pytestmark = pytest.mark.anyio

_REAL_ID = "ev_1111111111111111"
_BOGUS_ID = "ev_ffffffffffffffff"


@pytest.fixture(autouse=True)
def _clean_store():
    store_module.reset_store()
    app_module._STATE["bundle"] = None
    yield
    store_module.reset_store()
    app_module._STATE["bundle"] = None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client


def _investigation_with_finding() -> Investigation:
    now = datetime.now(UTC)
    hyp = Hypothesis(
        claim="Vendor VEND-1 was created and approved by the same user.",
        category=HypothesisCategory.VENDOR_INTEGRITY,
        status=HypothesisStatus.SUBMITTED,
        priority=90,
        supporting_evidence_ids=[_REAL_ID],
        candidate_exposure=Decimal("295120.00"),
        verdict_recommendation=VerdictRecommendation.CONFIRM,
    )
    return Investigation(
        engagement_id="eng",
        objective="audit vendor payments",
        status=InvestigationStatus.COMPLETED,
        hypotheses=[hyp],
        evidence_ids=[_REAL_ID],
        created_at=now,
        updated_at=now,
    )


class _StubPlanner:
    """A planner whose LLM cites both a real and a hallucinated evidence id."""

    name = "stub"

    def phrase_grounded_answer(self, question: str, facts: dict) -> str:
        return (
            "A candidate exposure of 295120.00 was found; see "
            f"{_REAL_ID} and also {_BOGUS_ID}."
        )


def test_llm_answer_strips_evidence_ids_not_in_investigation() -> None:
    inv = _investigation_with_finding()
    text, cited = build_answer(inv, "what did you find?", _StubPlanner())

    assert text.strip()
    assert _REAL_ID in text
    assert _BOGUS_ID not in text  # hallucinated id scrubbed from the prose
    assert cited == [_REAL_ID]  # only the investigation's real id is cited


def test_deterministic_answer_is_grounded_and_non_empty() -> None:
    inv = _investigation_with_finding()
    text, cited = build_answer(inv, "summarise the case", DeterministicPlanner())

    assert text.strip()
    assert "audit vendor payments" in text  # derived from real objective
    assert "VEND-1" in text  # derived from the real hypothesis claim
    assert "295120.00" in text  # the real candidate exposure, not invented
    assert cited == [_REAL_ID]
    # Every cited id must be one the investigation actually holds.
    allowed = set(inv.evidence_ids)
    assert all(eid in allowed for eid in cited)


def _minimal_dossier_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "dossier/invoices.csv",
            "invoice_id,vendor_id,amount,date\nINV-1,VEND-1,100.00,2024-01-05\n",
        )
        zf.writestr(
            "dossier/vendors.csv",
            "vendor_id,name,created_by,approved_by\nVEND-1,Acme,alice,alice\n",
        )
    return buf.getvalue()


async def test_messages_endpoint_produces_grounded_assistant_reply(
    client: AsyncClient,
) -> None:
    upload = await client.post(
        "/engagements/upload",
        files={"file": ("dossier.zip", _minimal_dossier_zip(), "application/zip")},
    )
    assert upload.status_code == 200, upload.text
    engagement_id = upload.json()["engagement_id"]

    created = await client.post(
        "/investigations",
        json={"engagement_id": engagement_id, "objective": "look for vendor fraud"},
    )
    assert created.status_code == 200, created.text
    investigation_id = created.json()["investigation_id"]

    question = "what have you found so far?"
    response = await client.post(
        f"/investigations/{investigation_id}/messages", json={"message": question}
    )
    assert response.status_code == 200, response.text
    inv = response.json()

    # Backward-compatible: the question is still recorded.
    assert question in inv["questions_for_auditor"]

    timeline = inv["timeline"]
    auditor_events = [e for e in timeline if e["kind"] == "auditor_message"]
    reply_events = [e for e in timeline if e["kind"] == "assistant_reply"]

    assert auditor_events, "an auditor_message event must be emitted"
    assert auditor_events[-1]["detail"] == question
    assert "at" in auditor_events[-1]

    assert reply_events, "an assistant_reply event must be emitted"
    reply = reply_events[-1]
    assert reply["detail"].strip(), "the grounded answer must be non-empty"
    assert "at" in reply
    assert isinstance(reply["evidence_ids"], list)

    # Every cited evidence id must be one the investigation actually holds.
    held = set(inv["evidence_ids"])
    for hyp in inv["hypotheses"]:
        held.update(hyp["supporting_evidence_ids"])
        held.update(hyp["contradicting_evidence_ids"])
    assert all(eid in held for eid in reply["evidence_ids"])
