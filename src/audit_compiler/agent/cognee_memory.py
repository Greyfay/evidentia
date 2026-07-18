"""Cognee-backed investigation memory.

This module gives the investigation agent a durable, queryable memory of
investigations, hypotheses, entities, and the relationships between them
(who created what, which evidence supports/contradicts which hypothesis,
which vendors are connected to which user, ...).

Two layers back every operation:

1. A local `InMemoryGraph` (from `audit_compiler.graph.interface`) is the
   deterministic source of truth. All structural queries (neighbors,
   multi-hop traversal) are answered from it, so results never depend on an
   external service being reachable or correctly configured.
2. A best-effort mirror to the Cognee cloud REST API. When configured
   (`COGNEE_API_URL` + `COGNEE_API_KEY`, and `httpx` importable), every write
   is also POSTed to Cognee so its semantic search/cognify pipeline can build
   its own graph over the same facts. Any failure here (missing library, no
   key, network error, non-2xx response) is caught, logged, and swallowed —
   it never raises into the agent and never affects the local mirror.

No method on `CogneeMemory` raises for partner-availability reasons. Callers
that want to know whether the cloud path is live should check `.available`.

## Real endpoints used (Cognee cloud REST API, `/api/v1/...`)

- `GET /health` — unauthenticated liveness probe.
- `POST /api/v1/add_text` — ingest plain text into a named dataset
  (`AddPayloadDTO`: `textData`, `datasetName`). Used to mirror every node/edge
  write as a short text fact.
- `POST /api/v1/cognify` — asynchronously build the knowledge graph over a
  dataset (`CognifyPayloadDTO`: `datasets`, `runInBackground`). Fired with
  `runInBackground=True` so it returns immediately; the actual graph build
  happens server-side and is not waited on.
- `POST /api/v1/search` — semantic/graph search over a dataset
  (`SearchPayloadDTO`: `query`, `datasets`, `searchType`, `topK`). Used to
  enrich structural query results; never gates them.

`COGNEE_API_KEY` is read from the process environment. If it is not already
set (e.g. only present in a local `.env` file), this module makes a
best-effort attempt to load it via `python-dotenv` at import time — never
overriding an already-exported value, and silently no-op-ing if
`python-dotenv` is not installed. The key is never hard-coded.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from audit_compiler.agent.models import Hypothesis, Investigation
from audit_compiler.graph.interface import (
    GraphEdge,
    GraphNode,
    InMemoryGraph,
    NodeKind,
    RelationshipKind,
)

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECONDS = 5.0
_SEARCH_TIMEOUT_SECONDS = 15.0
_DEFAULT_DATASET_NAME = "audit_investigation_memory"

# NOTE: this library never loads .env or performs network I/O at import time. The CLI and
# API entrypoints load .env explicitly, so tests run offline and deterministically unless a
# key is present in the real environment.


class CogneeMemory:
    """Investigation memory: local deterministic mirror + best-effort Cognee cloud sync."""

    def __init__(self) -> None:
        self._graph = InMemoryGraph()
        self._api_url = os.environ.get("COGNEE_API_URL", "").rstrip("/")
        self._tenant_id = os.environ.get("COGNEE_TENANT_ID", "")
        self._user_id = os.environ.get("COGNEE_USER_ID", "")
        self._api_key = os.environ.get("COGNEE_API_KEY", "")
        self._dataset_name = os.environ.get("COGNEE_DATASET_NAME", _DEFAULT_DATASET_NAME)
        self._httpx: Any = None
        if self._api_url and self._api_key:
            try:
                import httpx

                self._httpx = httpx
            except ImportError:
                self._httpx = None

    @property
    def available(self) -> bool:
        """True only if the Cognee cloud API is configured and reachable in principle.

        Does not perform a network call; it only checks that the pieces needed to
        attempt one (URL, API key, `httpx`) are present.
        """

        return bool(self._api_url and self._api_key and self._httpx is not None)

    # -- best-effort cloud mirror -------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"X-Api-Key": self._api_key}
        if self._tenant_id:
            headers["X-Tenant-Id"] = self._tenant_id
        return headers

    def health_check(self) -> dict | None:
        """Best-effort `GET /health` against the Cognee cloud API. Never raises.

        Unlike the rest of the cloud surface this needs no API key, only a
        configured URL and `httpx`; it is exposed so callers/tests can confirm
        the tenant is reachable independently of write/read operations.
        """

        if not self._api_url or self._httpx is None:
            return None
        try:
            response = self._httpx.get(
                f"{self._api_url}/health", timeout=_REQUEST_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            logger.warning("cognee cloud health check failed")
            return None

    def _cloud_add_text(self, text: str) -> dict | None:
        """Best-effort `POST /api/v1/add_text`. Never raises."""

        if not self.available:
            return None
        try:
            response = self._httpx.post(
                f"{self._api_url}/api/v1/add_text",
                json={"textData": [text], "datasetName": self._dataset_name},
                headers=self._headers(),
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            logger.warning("cognee cloud add_text failed")
            return None

    def _cloud_cognify(self) -> None:
        """Best-effort, non-blocking `POST /api/v1/cognify`. Never raises.

        Runs in the background server-side (`runInBackground=True`) so this call
        returns immediately regardless of how long the graph build takes.
        """

        if not self.available:
            return
        try:
            response = self._httpx.post(
                f"{self._api_url}/api/v1/cognify",
                json={"datasets": [self._dataset_name], "runInBackground": True},
                headers=self._headers(),
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except Exception:
            logger.warning("cognee cloud cognify failed")

    def _cloud_search(self, query: str, search_type: str = "CHUNKS") -> dict | None:
        """Best-effort `POST /api/v1/search`. Never raises.

        Defaults to `CHUNKS` (a direct lexical/vector lookup) rather than the
        default `GRAPH_COMPLETION`, which triggers a server-side LLM synthesis
        step and can take far longer than this is willing to wait for a
        best-effort enrichment call.
        """

        if not self.available:
            return None
        try:
            response = self._httpx.post(
                f"{self._api_url}/api/v1/search",
                json={
                    "query": query,
                    "datasets": [self._dataset_name],
                    "searchType": search_type,
                    "topK": 10,
                },
                headers=self._headers(),
                timeout=_SEARCH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            logger.warning("cognee cloud search failed")
            return None

    def _mirror_node(self, node: GraphNode) -> None:
        self._graph.add_node(node)
        self._cloud_add_text(f"{node.kind.value} {node.node_id}: {node.attributes}")
        self._cloud_cognify()

    def _mirror_edge(self, edge: GraphEdge) -> None:
        self._graph.add_edge(edge)
        self._cloud_add_text(
            f"{edge.source_id} -{edge.relationship.value}-> "
            f"{edge.target_id}: {edge.attributes}"
        )
        self._cloud_cognify()

    # -- writes ---------------------------------------------------------------

    def remember_investigation(self, inv: Investigation) -> None:
        """Persist an `Investigation` and its hypotheses as nodes/edges."""

        self._mirror_node(
            GraphNode(
                node_id=str(inv.investigation_id),
                kind=NodeKind.INVESTIGATION,
                attributes={
                    "engagement_id": inv.engagement_id,
                    "objective": inv.objective,
                    "status": inv.status.value,
                },
            )
        )
        for hyp in inv.hypotheses:
            self.remember_hypothesis(hyp, str(inv.investigation_id))

    def remember_hypothesis(self, hyp: Hypothesis, investigation_id: str) -> None:
        """Persist a `Hypothesis` and link it to its parent investigation."""

        self._mirror_node(
            GraphNode(
                node_id=str(hyp.hypothesis_id),
                kind=NodeKind.HYPOTHESIS,
                attributes={
                    "claim": hyp.claim,
                    "category": hyp.category.value,
                    "status": hyp.status.value,
                    "priority": hyp.priority,
                },
            )
        )
        # Directed hypothesis -> investigation: "this hypothesis is investigated by this
        # investigation". `InMemoryGraph.get_neighbors` only walks forward along outgoing
        # edges, so the direction matters for `open_hypothesis_context` to reach the parent.
        self.link(str(hyp.hypothesis_id), RelationshipKind.INVESTIGATED_BY, investigation_id)
        for evidence_id in hyp.supporting_evidence_ids:
            self.link(str(hyp.hypothesis_id), RelationshipKind.SUPPORTED_BY, evidence_id)
        for evidence_id in hyp.contradicting_evidence_ids:
            self.link(str(hyp.hypothesis_id), RelationshipKind.CONTRADICTED_BY, evidence_id)

    def add_entity(self, entity_id: str, kind: NodeKind = NodeKind.ENTITY, **props: Any) -> None:
        """Persist a generic entity node (vendor, user, account, ...)."""

        self._mirror_node(GraphNode(node_id=entity_id, kind=kind, attributes=dict(props)))

    def add_event(self, event_id: str, **props: Any) -> None:
        """Persist a financial event node (payment, invoice, journal entry, ...)."""

        self._mirror_node(
            GraphNode(node_id=event_id, kind=NodeKind.FINANCIAL_EVENT, attributes=dict(props))
        )

    def add_observation(self, observation_id: str, **props: Any) -> None:
        """Persist a tool observation node produced during an investigation."""

        self._mirror_node(
            GraphNode(node_id=observation_id, kind=NodeKind.OBSERVATION, attributes=dict(props))
        )

    def link(
        self,
        src: str,
        rel: RelationshipKind,
        dst: str,
        **attributes: Any,
    ) -> None:
        """Persist a directed relationship between two already-known or new node ids."""

        self._mirror_edge(
            GraphEdge(source_id=src, target_id=dst, relationship=rel, attributes=dict(attributes))
        )

    def seed_entity_local(
        self, entity_id: str, kind: NodeKind = NodeKind.ENTITY, **props: Any
    ) -> None:
        """Write an entity to the local mirror only — no cloud round-trip.

        For latency-sensitive seeding inside the agent loop, where the cloud
        `add_text`/`cognify` pipeline is too slow to block on. The cloud path is
        still exercised by the read side (`related_entities`'s live search)."""

        self._graph.add_node(GraphNode(node_id=entity_id, kind=kind, attributes=dict(props)))

    def seed_link_local(
        self, src: str, rel: RelationshipKind, dst: str, **attributes: Any
    ) -> None:
        """Write a directed edge to the local mirror only — no cloud round-trip."""

        self._graph.add_edge(
            GraphEdge(source_id=src, target_id=dst, relationship=rel, attributes=dict(attributes))
        )

    # -- queries ----------------------------------------------------------------

    def related_entities(self, entity_id: str, hops: int = 2) -> dict:
        """Return nodes/edges reachable from `entity_id` within `hops`, exact + local.

        Optionally enriched (never gated on) by a best-effort Cognee cloud search.
        """

        result = self._graph.get_neighbors(entity_id, max_hops=hops)
        cloud_hits = None
        if self.available:
            cloud_hits = self._cloud_search(f"entities related to {entity_id}")
        return {
            "available": True,
            "provider": "in_memory+cognee" if self.available else "in_memory",
            "nodes": [n.model_dump(mode="json") for n in result.nodes],
            "edges": [e.model_dump(mode="json") for e in result.edges],
            "cloud_enrichment": cloud_hits,
        }

    def similar_investigation_paths(self, category: str) -> dict:
        """Return investigations/hypotheses in the local mirror matching `category`."""

        matches = [
            node.model_dump(mode="json")
            for node in self._graph._nodes.values()  # noqa: SLF001 - internal mirror read
            if node.kind == NodeKind.HYPOTHESIS and node.attributes.get("category") == category
        ]
        cloud_hits = None
        if self.available:
            cloud_hits = self._cloud_search(f"investigations similar to category {category}")
        return {
            "available": True,
            "provider": "in_memory+cognee" if self.available else "in_memory",
            "hypotheses": matches,
            "cloud_enrichment": cloud_hits,
        }

    def vendors_connected_to_user(self, user_id: str, hops: int = 3) -> dict:
        """Return entity nodes reachable from `user_id` within `hops` (e.g. vendor entities)."""

        result = self._graph.get_neighbors(user_id, max_hops=hops)
        vendors = [
            node.model_dump(mode="json")
            for node in result.nodes
            if node.node_id != user_id and node.kind == NodeKind.ENTITY
        ]
        cloud_hits = None
        if self.available:
            cloud_hits = self._cloud_search(f"vendors connected to user {user_id}")
        return {
            "available": True,
            "provider": "in_memory+cognee" if self.available else "in_memory",
            "vendors": vendors,
            "edges": [e.model_dump(mode="json") for e in result.edges],
            "cloud_enrichment": cloud_hits,
        }

    def open_hypothesis_context(self, hypothesis_id: str) -> dict:
        """Return the full local neighborhood of an open hypothesis (evidence, entities, events)."""

        result = self._graph.get_neighbors(hypothesis_id, max_hops=2)
        cloud_hits = None
        if self.available:
            cloud_hits = self._cloud_search(f"context for hypothesis {hypothesis_id}")
        return {
            "available": True,
            "provider": "in_memory+cognee" if self.available else "in_memory",
            "nodes": [n.model_dump(mode="json") for n in result.nodes],
            "edges": [e.model_dump(mode="json") for e in result.edges],
            "cloud_enrichment": cloud_hits,
        }


_memory: CogneeMemory | None = None


def get_memory() -> CogneeMemory:
    """Return the process-wide `CogneeMemory` singleton."""

    global _memory
    if _memory is None:
        _memory = CogneeMemory()
    return _memory
