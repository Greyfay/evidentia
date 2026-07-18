"""Tests for the Cognee-backed investigation memory and its agent tools.

Most of these tests exercise the no-credentials-configured path deliberately
(an autouse fixture strips `COGNEE_API_KEY`): `CogneeMemory.available` must be
False and every method must work against the deterministic local
`InMemoryGraph` mirror without ever raising — including when the (unreachable)
cloud path is simulated to fail outright.

One test (`test_live_cognee_cloud_smoke`) is the exception: it restores the
real `COGNEE_API_KEY` (loaded from `.env` at import time, before the autouse
fixture strips it per-test) and hits the actual Cognee cloud API. It is
skipped automatically when no real key is configured, so CI without one still
passes.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from audit_compiler.agent import cognee_memory as cognee_memory_module
from audit_compiler.agent.cognee_memory import CogneeMemory, get_memory
from audit_compiler.agent.cognee_tools import (
    COGNEE_TOOLS,
    find_other_vendors_connected_to_user,
    find_related_entities,
    find_similar_investigation_paths,
    retrieve_open_hypothesis_context,
)
from audit_compiler.agent.context import AgentContext
from audit_compiler.agent.models import (
    Hypothesis,
    HypothesisCategory,
    Investigation,
    ToolResult,
)
from audit_compiler.graph.interface import NodeKind, RelationshipKind

# Captured at import time, before the autouse fixture below strips
# `COGNEE_API_KEY` for every test. Importing `cognee_memory_module` above
# already triggered its best-effort `.env` load, so this reflects whatever
# real key (if any) is configured for this environment.
_REAL_COGNEE_API_URL = os.environ.get("COGNEE_API_URL", "")
_REAL_COGNEE_TENANT_ID = os.environ.get("COGNEE_TENANT_ID", "")
_REAL_COGNEE_USER_ID = os.environ.get("COGNEE_USER_ID", "")
_REAL_COGNEE_API_KEY = os.environ.get("COGNEE_API_KEY", "")


@pytest.fixture(autouse=True)
def _no_cognee_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COGNEE_API_KEY", raising=False)
    monkeypatch.setenv("COGNEE_API_URL", "https://example.cognee.ai")
    monkeypatch.setenv("COGNEE_TENANT_ID", "tenant-1")
    monkeypatch.setenv("COGNEE_USER_ID", "user-1")


@pytest.fixture()
def ctx() -> AgentContext:
    return AgentContext(dossier=None)  # type: ignore[arg-type]


def _now() -> datetime:
    return datetime(2026, 7, 18, tzinfo=UTC)


def test_memory_unavailable_without_api_key() -> None:
    memory = CogneeMemory()
    assert memory.available is False


def test_get_memory_returns_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cognee_memory_module, "_memory", None)
    first = get_memory()
    second = get_memory()
    assert first is second


def test_remember_investigation_and_hypothesis_never_raise() -> None:
    memory = CogneeMemory()
    hyp = Hypothesis(
        claim="vendor invoice split to avoid approval",
        category=HypothesisCategory.SPLIT_PAYMENT,
    )
    inv = Investigation(
        engagement_id="ENG-1",
        objective="find split payments",
        hypotheses=[hyp],
        created_at=_now(),
        updated_at=_now(),
    )

    memory.remember_investigation(inv)

    result = memory.open_hypothesis_context(str(hyp.hypothesis_id))
    assert result["available"] is True
    node_ids = {n["node_id"] for n in result["nodes"]}
    assert str(inv.investigation_id) in node_ids


def test_add_entity_add_event_add_observation_and_link_never_raise() -> None:
    memory = CogneeMemory()
    memory.add_entity("user-1", kind=NodeKind.ENTITY, name="Jane Auditor")
    memory.add_entity("vendor-1", kind=NodeKind.ENTITY, name="Acme Supplies")
    memory.add_event("payment-1", amount="1000.00")
    memory.add_observation("obs-1", tool_name="find_related_entities")

    memory.link("user-1", RelationshipKind.CREATED, "payment-1")
    memory.link("payment-1", RelationshipKind.PAID, "vendor-1")

    result = memory.related_entities("user-1", hops=2)
    node_ids = {n["node_id"] for n in result["nodes"]}
    assert {"user-1", "payment-1", "vendor-1"}.issubset(node_ids)


def test_cloud_outage_is_swallowed_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COGNEE_API_KEY", "secret-key")

    class _ExplodingHttpx:
        @staticmethod
        def post(*args: object, **kwargs: object) -> object:
            raise RuntimeError("simulated network outage")

    memory = CogneeMemory()
    memory._httpx = _ExplodingHttpx()  # simulate httpx being importable but the network down
    assert memory.available is True

    memory.add_entity("user-1", kind=NodeKind.ENTITY, name="Jane Auditor")
    memory.add_entity("vendor-1", kind=NodeKind.ENTITY, name="Acme Supplies")
    memory.link("user-1", RelationshipKind.CREATED, "vendor-1")

    result = memory.related_entities("user-1", hops=1)
    assert result["available"] is True
    assert {n["node_id"] for n in result["nodes"]} == {"user-1", "vendor-1"}


def test_related_entities_multi_hop_user_vendor_payment() -> None:
    memory = CogneeMemory()
    memory.add_entity("user-1", kind=NodeKind.ENTITY)
    memory.add_entity("vendor-1", kind=NodeKind.ENTITY)
    memory.add_event("payment-1")
    memory.link("user-1", RelationshipKind.APPROVED, "payment-1")
    memory.link("payment-1", RelationshipKind.PAID, "vendor-1")

    one_hop = memory.related_entities("user-1", hops=1)
    assert {n["node_id"] for n in one_hop["nodes"]} == {"user-1", "payment-1"}

    two_hop = memory.related_entities("user-1", hops=2)
    assert {n["node_id"] for n in two_hop["nodes"]} == {"user-1", "payment-1", "vendor-1"}


def test_vendors_connected_to_user_returns_only_entity_nodes() -> None:
    memory = CogneeMemory()
    memory.add_entity("user-1", kind=NodeKind.ENTITY)
    memory.add_entity("vendor-1", kind=NodeKind.ENTITY, name="Acme Supplies")
    memory.add_event("payment-1")
    memory.link("user-1", RelationshipKind.APPROVED, "payment-1")
    memory.link("payment-1", RelationshipKind.PAID, "vendor-1")

    result = memory.vendors_connected_to_user("user-1", hops=3)
    vendor_ids = {v["node_id"] for v in result["vendors"]}
    assert vendor_ids == {"vendor-1"}


def test_similar_investigation_paths_matches_by_category() -> None:
    memory = CogneeMemory()
    hyp = Hypothesis(claim="cutoff timing issue", category=HypothesisCategory.CUTOFF)
    inv = Investigation(
        engagement_id="ENG-2",
        objective="find cutoff issues",
        hypotheses=[hyp],
        created_at=_now(),
        updated_at=_now(),
    )
    memory.remember_investigation(inv)

    result = memory.similar_investigation_paths(HypothesisCategory.CUTOFF.value)
    assert any(h["node_id"] == str(hyp.hypothesis_id) for h in result["hypotheses"])

    empty = memory.similar_investigation_paths(HypothesisCategory.VENDOR_INTEGRITY.value)
    assert empty["hypotheses"] == []


# -- tools ------------------------------------------------------------------


def test_find_related_entities_tool_graceful_when_empty(
    monkeypatch: pytest.MonkeyPatch, ctx: AgentContext
) -> None:
    monkeypatch.setattr(cognee_memory_module, "_memory", None)
    result = find_related_entities(ctx, {"entity_id": "nonexistent"})
    assert isinstance(result, ToolResult)
    assert result.ok is True
    assert result.structured_result["nodes"] == []
    assert result.errors


def test_find_related_entities_tool_returns_real_relationships(
    monkeypatch: pytest.MonkeyPatch, ctx: AgentContext
) -> None:
    monkeypatch.setattr(cognee_memory_module, "_memory", None)
    memory = get_memory()
    memory.add_entity("user-1", kind=NodeKind.ENTITY)
    memory.add_entity("vendor-1", kind=NodeKind.ENTITY)
    memory.link("user-1", RelationshipKind.CREATED, "vendor-1")

    result = find_related_entities(ctx, {"entity_id": "user-1", "hops": 1})
    assert result.ok is True
    node_ids = {n["node_id"] for n in result.structured_result["nodes"]}
    assert node_ids == {"user-1", "vendor-1"}


def test_find_related_entities_tool_requires_entity_id(ctx: AgentContext) -> None:
    result = find_related_entities(ctx, {})
    assert result.ok is False
    assert result.errors


def test_find_other_vendors_connected_to_user_tool(
    monkeypatch: pytest.MonkeyPatch, ctx: AgentContext
) -> None:
    monkeypatch.setattr(cognee_memory_module, "_memory", None)
    memory = get_memory()
    memory.add_entity("user-1", kind=NodeKind.ENTITY)
    memory.add_entity("vendor-1", kind=NodeKind.ENTITY)
    memory.add_event("payment-1")
    memory.link("user-1", RelationshipKind.APPROVED, "payment-1")
    memory.link("payment-1", RelationshipKind.PAID, "vendor-1")

    result = find_other_vendors_connected_to_user(ctx, {"user_id": "user-1", "hops": 3})
    assert result.ok is True
    vendor_ids = {v["node_id"] for v in result.structured_result["vendors"]}
    assert vendor_ids == {"vendor-1"}


def test_find_similar_investigation_paths_tool(
    monkeypatch: pytest.MonkeyPatch, ctx: AgentContext
) -> None:
    monkeypatch.setattr(cognee_memory_module, "_memory", None)
    memory = get_memory()
    hyp = Hypothesis(claim="test", category=HypothesisCategory.OTHER)
    inv = Investigation(
        engagement_id="ENG-3",
        objective="obj",
        hypotheses=[hyp],
        created_at=_now(),
        updated_at=_now(),
    )
    memory.remember_investigation(inv)

    result = find_similar_investigation_paths(ctx, {"category": HypothesisCategory.OTHER.value})
    assert result.ok is True
    assert len(result.structured_result["hypotheses"]) == 1


def test_retrieve_open_hypothesis_context_tool_graceful_when_empty(
    monkeypatch: pytest.MonkeyPatch, ctx: AgentContext
) -> None:
    monkeypatch.setattr(cognee_memory_module, "_memory", None)
    result = retrieve_open_hypothesis_context(ctx, {"hypothesis_id": "nonexistent"})
    assert result.ok is True
    assert result.structured_result["nodes"] == []
    assert result.errors


def test_cognee_tools_dict_matches_functions() -> None:
    assert set(COGNEE_TOOLS) == {
        "find_related_entities",
        "find_similar_investigation_paths",
        "find_other_vendors_connected_to_user",
        "retrieve_open_hypothesis_context",
    }
    assert COGNEE_TOOLS["find_related_entities"] is find_related_entities


# -- live cloud smoke test ----------------------------------------------------


@pytest.mark.skipif(
    not _REAL_COGNEE_API_KEY,
    reason="requires a live COGNEE_API_KEY (set it in .env to run this test)",
)
def test_live_cognee_cloud_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the real Cognee cloud API: health check + add_text -> search round trip.

    Skipped (not xfail'd) when no real key is configured, so CI without one still
    passes. When it does run, every assertion here reflects an actual network call
    to the live tenant — no simulation, no monkeypatched transport.
    """

    monkeypatch.setenv("COGNEE_API_URL", _REAL_COGNEE_API_URL)
    monkeypatch.setenv("COGNEE_TENANT_ID", _REAL_COGNEE_TENANT_ID)
    monkeypatch.setenv("COGNEE_USER_ID", _REAL_COGNEE_USER_ID)
    monkeypatch.setenv("COGNEE_API_KEY", _REAL_COGNEE_API_KEY)

    memory = CogneeMemory()
    assert memory.available is True

    health = memory.health_check()
    assert health is not None, "GET /health returned no body — is the tenant reachable?"
    assert health.get("status") == "healthy"

    # add_text -> search round trip. cognify runs server-side in the background, so
    # the search result may or may not have indexed this exact fact yet; what this
    # asserts is that both calls complete without raising and return a real,
    # structured (non-None) response from the live API.
    entity_id = "smoke-test-entity-cognee-memory"
    memory.add_entity(entity_id, kind=NodeKind.ENTITY, name="Live Smoke Test Entity")

    result = memory.related_entities(entity_id, hops=1)
    assert result["available"] is True
    assert entity_id in {n["node_id"] for n in result["nodes"]}  # local mirror, always exact
    assert result["cloud_enrichment"] is not None, (
        "cloud search returned None — the live add_text/search round trip failed"
    )
    assert isinstance(result["cloud_enrichment"], list)
