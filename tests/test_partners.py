"""Tests for the partner technology integration layer (LLM, graph, external).

These tests exercise the no-credentials-configured path exclusively: they
assert that every partner surface degrades to a working, typed fallback and
never raises, and that the in-memory graph and evidence-citation validation
actually work.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from audit_compiler.external.interface import ExternalCheck, NullVerifier, get_verifier
from audit_compiler.graph.interface import (
    EvidenceGraph,
    GraphEdge,
    GraphNode,
    InMemoryGraph,
    NodeKind,
    RelationshipKind,
    get_graph,
)
from audit_compiler.llm.interface import (
    Classification,
    Explanation,
    LLMInterpreter,
    NullInterpreter,
    TermNormalization,
    get_interpreter,
    split_evidence_citations,
    validate_evidence_citations,
)


@pytest.fixture(autouse=True)
def _no_partner_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)


def test_get_interpreter_without_key_returns_null_and_never_raises() -> None:
    interpreter = get_interpreter()
    assert isinstance(interpreter, NullInterpreter)
    assert isinstance(interpreter, LLMInterpreter)

    normalized = interpreter.normalize_terms(["Anzahlung"], target_language="en")
    assert isinstance(normalized, TermNormalization)
    assert normalized.available is False
    assert normalized.normalized_terms == {}

    classification = interpreter.classify_description("some ambiguous text", ["a", "b"])
    assert isinstance(classification, Classification)
    assert classification.available is False
    assert classification.label is None

    explanation = interpreter.explain_case({"case": "x"}, allowed_evidence_ids={"e1"})
    assert isinstance(explanation, Explanation)
    assert explanation.available is False
    assert explanation.cited_evidence_ids == ()

    hypotheses = interpreter.generate_counter_hypotheses({"case": "x"})
    assert hypotheses == []


def test_get_graph_without_cognee_or_key_returns_working_in_memory_graph() -> None:
    graph = get_graph()
    assert isinstance(graph, InMemoryGraph)
    assert isinstance(graph, EvidenceGraph)

    graph.add_node(GraphNode(node_id="entity-1", kind=NodeKind.ENTITY))
    graph.add_node(GraphNode(node_id="event-1", kind=NodeKind.FINANCIAL_EVENT))
    graph.add_edge(
        GraphEdge(source_id="entity-1", target_id="event-1", relationship=RelationshipKind.CREATED)
    )

    result = graph.get_neighbors("entity-1")
    assert result.available is True
    node_ids = {n.node_id for n in result.nodes}
    assert "event-1" in node_ids


def test_get_verifier_defaults_to_null_and_requires_explicit_opt_in() -> None:
    verifier = get_verifier()
    assert isinstance(verifier, NullVerifier)

    # Even if a caller tries to opt in without a key configured, it still degrades.
    verifier_still_null = get_verifier(enabled=True)
    assert isinstance(verifier_still_null, NullVerifier)

    check = verifier.verify_entity("Acme GmbH", "supplier context")
    assert isinstance(check, ExternalCheck)
    assert check.available is False
    assert check.verified is None


def test_in_memory_graph_add_and_multi_hop_query() -> None:
    graph = InMemoryGraph()
    graph.add_node(GraphNode(node_id="entity-1", kind=NodeKind.ENTITY))
    graph.add_node(GraphNode(node_id="event-1", kind=NodeKind.FINANCIAL_EVENT))
    graph.add_node(GraphNode(node_id="evidence-1", kind=NodeKind.EVIDENCE_REF))
    graph.add_node(GraphNode(node_id="evidence-2", kind=NodeKind.EVIDENCE_REF))

    graph.add_edge(
        GraphEdge(source_id="entity-1", target_id="event-1", relationship=RelationshipKind.CREATED)
    )
    graph.add_edge(
        GraphEdge(
            source_id="event-1", target_id="evidence-1", relationship=RelationshipKind.SUPPORTED_BY
        )
    )
    graph.add_edge(
        GraphEdge(
            source_id="event-1",
            target_id="evidence-2",
            relationship=RelationshipKind.CONTRADICTED_BY,
        )
    )

    one_hop = graph.get_neighbors("entity-1", max_hops=1)
    assert {n.node_id for n in one_hop.nodes} == {"entity-1", "event-1"}

    two_hop = graph.get_neighbors("entity-1", max_hops=2)
    assert {n.node_id for n in two_hop.nodes} == {"entity-1", "event-1", "evidence-1", "evidence-2"}

    filtered = graph.get_neighbors(
        "entity-1",
        max_hops=2,
        relationships={RelationshipKind.CREATED, RelationshipKind.SUPPORTED_BY},
    )
    filtered_ids = {n.node_id for n in filtered.nodes}
    assert filtered_ids == {"entity-1", "event-1", "evidence-1"}
    assert "evidence-2" not in filtered_ids

    unknown = graph.get_neighbors("does-not-exist")
    assert unknown.available is True
    assert unknown.nodes == ()
    assert unknown.edges == ()


def test_validate_evidence_citations_rejects_unknown_id() -> None:
    allowed = {"e1", "e2"}
    validate_evidence_citations({"e1"}, allowed)  # does not raise

    with pytest.raises(ValueError, match="e3"):
        validate_evidence_citations({"e1", "e3"}, allowed)


def test_split_evidence_citations_separates_allowed_from_rejected() -> None:
    allowed = {"e1", "e2"}
    cited, rejected = split_evidence_citations(["e1", "e3", "e2", "e1", "e4"], allowed)
    assert cited == ("e1", "e2")
    assert rejected == ("e3", "e4")


def test_explanation_model_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Explanation(available=True, provider="null", not_a_real_field="x")  # type: ignore[call-arg]
