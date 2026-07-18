"""Evidence graph interface for the partner integration layer.

The graph relates entities, financial events, evidence, control results, and
findings so a case can be explored multi-hop (e.g. "which evidence supports
the events that this control result depends on, and what contradicts it?").
The graph is a navigation and suggestion aid; it never substitutes for the
deterministic control results and cases produced by the compiler.

Every method degrades gracefully: a missing/unconfigured `cognee` install
falls back to a fully functional in-memory adjacency graph rather than raising.
"""

from __future__ import annotations

import os
from collections import deque
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class NodeKind(StrEnum):
    """The kinds of nodes the evidence graph can hold."""

    ENTITY = "entity"
    FINANCIAL_EVENT = "financial_event"
    EVIDENCE_REF = "evidence_ref"
    CONTROL_RESULT = "control_result"
    FINDING = "finding"


class RelationshipKind(StrEnum):
    """The kinds of directed relationships the evidence graph can hold."""

    CREATED = "created"
    APPROVED = "approved"
    POSTED = "posted"
    PAID = "paid"
    SETTLES = "settles"
    SUPPORTED_BY = "supported_by"
    DERIVED_FROM = "derived_from"
    CONTRADICTED_BY = "contradicted_by"
    DISMISSED_BY = "dismissed_by"
    AFFECTS = "affects"


class GraphNode(BaseModel):
    """A node in the evidence graph."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    kind: NodeKind
    attributes: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """A directed relationship between two nodes in the evidence graph."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relationship: RelationshipKind
    attributes: dict[str, Any] = Field(default_factory=dict)


class GraphQueryResult(BaseModel):
    """The result of a (possibly multi-hop) neighbour query."""

    model_config = ConfigDict(extra="forbid")

    available: bool
    provider: str
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    error: str | None = None


@runtime_checkable
class EvidenceGraph(Protocol):
    """Storage and multi-hop navigation over the evidence graph. No method may raise."""

    def add_node(self, node: GraphNode) -> None:
        """Add or update a node. Idempotent for the same `node_id`."""
        ...

    def add_edge(self, edge: GraphEdge) -> None:
        """Add a directed relationship between two nodes."""
        ...

    def get_neighbors(
        self,
        node_id: str,
        max_hops: int = 1,
        relationships: set[RelationshipKind] | None = None,
    ) -> GraphQueryResult:
        """Return nodes/edges reachable from `node_id` within `max_hops`.

        `relationships`, if given, restricts traversal to those relationship kinds.
        """
        ...


class InMemoryGraph:
    """A dict-adjacency `EvidenceGraph` that works with no external dependency."""

    provider = "in_memory"

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._outgoing: dict[str, list[GraphEdge]] = {}

    def add_node(self, node: GraphNode) -> None:
        self._nodes[node.node_id] = node
        self._outgoing.setdefault(node.node_id, [])

    def add_edge(self, edge: GraphEdge) -> None:
        for node_id in (edge.source_id, edge.target_id):
            self._nodes.setdefault(node_id, GraphNode(node_id=node_id, kind=NodeKind.ENTITY))
        self._edges.append(edge)
        self._outgoing.setdefault(edge.source_id, []).append(edge)
        self._outgoing.setdefault(edge.target_id, [])

    def get_neighbors(
        self,
        node_id: str,
        max_hops: int = 1,
        relationships: set[RelationshipKind] | None = None,
    ) -> GraphQueryResult:
        if node_id not in self._nodes:
            return GraphQueryResult(available=True, provider=self.provider, nodes=(), edges=())

        visited_nodes: set[str] = {node_id}
        visited_edges: list[GraphEdge] = []
        frontier: deque[tuple[str, int]] = deque([(node_id, 0)])
        while frontier:
            current, depth = frontier.popleft()
            if depth >= max_hops:
                continue
            for edge in self._outgoing.get(current, ()):
                if relationships is not None and edge.relationship not in relationships:
                    continue
                visited_edges.append(edge)
                neighbor = edge.target_id if edge.source_id == current else edge.source_id
                if neighbor not in visited_nodes:
                    visited_nodes.add(neighbor)
                    frontier.append((neighbor, depth + 1))

        nodes = tuple(self._nodes[n] for n in visited_nodes if n in self._nodes)
        return GraphQueryResult(
            available=True, provider=self.provider, nodes=nodes, edges=tuple(visited_edges)
        )


def get_graph() -> EvidenceGraph:
    """Return a `CogneeGraph` if `cognee` is importable and configured, else in-memory.

    Cognee itself needs an underlying LLM to build/query the graph, so it is only
    selected when both the library imports and an LLM key (`OPENAI_API_KEY`) is
    present; otherwise the fully-functional `InMemoryGraph` is used.
    """

    try:
        import cognee  # noqa: F401
    except ImportError:
        return InMemoryGraph()

    if not os.environ.get("OPENAI_API_KEY"):
        return InMemoryGraph()

    try:
        from audit_compiler.graph.cognee_adapter import CogneeGraph

        return CogneeGraph()
    except Exception:
        return InMemoryGraph()
