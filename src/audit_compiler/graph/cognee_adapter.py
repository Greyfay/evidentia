"""Cognee-backed `EvidenceGraph`.

`cognee` is an optional dependency and is imported lazily so that a codebase
without it installed never fails to import this module. Cognee's own graph
construction (`cognify`) is itself LLM-backed and asynchronous, and its public
search surface is oriented around semantic queries rather than exact
multi-hop adjacency traversal of caller-defined node/edge ids.

To keep `get_neighbors` exact and deterministic (required for evidence
provenance), `CogneeGraph` keeps a local `InMemoryGraph` mirror as the source
of truth for structural traversal, and best-effort mirrors nodes/edges into
cognee for its semantic/document-linking capabilities. Any cognee failure
(missing library, no LLM key, network error) degrades that best-effort mirror
silently; it never affects the deterministic local graph or raises into the
pipeline.
"""

from __future__ import annotations

import asyncio
from typing import Any

from audit_compiler.graph.interface import (
    GraphEdge,
    GraphNode,
    GraphQueryResult,
    InMemoryGraph,
    RelationshipKind,
)


def _describe_node(node: GraphNode) -> str:
    return f"{node.kind.value} {node.node_id}: {node.attributes}"


def _describe_edge(edge: GraphEdge) -> str:
    return f"{edge.source_id} -{edge.relationship.value}-> {edge.target_id}: {edge.attributes}"


class CogneeGraph:
    """`EvidenceGraph` that mirrors structure locally and cognee semantically."""

    provider = "cognee"

    def __init__(self) -> None:
        # Deferred import: `cognee` is an optional dependency.
        import cognee

        self._cognee = cognee
        self._mirror = InMemoryGraph()

    def _run_best_effort(self, coro: Any) -> None:
        try:
            asyncio.run(coro)
        except Exception:
            # Cognee is a best-effort semantic mirror; failures here must never
            # affect the deterministic local graph or raise into the pipeline.
            pass

    def add_node(self, node: GraphNode) -> None:
        self._mirror.add_node(node)
        self._run_best_effort(self._cognee.add(_describe_node(node)))

    def add_edge(self, edge: GraphEdge) -> None:
        self._mirror.add_edge(edge)
        self._run_best_effort(self._cognee.add(_describe_edge(edge)))

    def get_neighbors(
        self,
        node_id: str,
        max_hops: int = 1,
        relationships: set[RelationshipKind] | None = None,
    ) -> GraphQueryResult:
        result = self._mirror.get_neighbors(node_id, max_hops=max_hops, relationships=relationships)
        return GraphQueryResult(
            available=result.available,
            provider=self.provider,
            nodes=result.nodes,
            edges=result.edges,
            error=result.error,
        )
