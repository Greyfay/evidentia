"""Cognee-backed agent tools: investigation memory and relationship navigation.

These tools share the same shape as the deterministic tool layer —
`(ctx, args) -> ToolResult` — so they can be merged into the same planner
allow-list. Unlike the deterministic tools, they never assert monetary truth:
DuckDB and the compiled dossier remain the sole authority for amounts. These
tools only ever return relationship/context data (node ids, edge kinds) drawn
from the investigation memory, so the planner can decide where to look next.

Every tool degrades gracefully: if Cognee cloud memory is unavailable, the
local deterministic mirror still answers structural queries; if the mirror is
empty, the tool returns `ok=True` with an empty result and a note, never a
fabricated answer.
"""

from __future__ import annotations

from typing import Any

from audit_compiler.agent.cognee_memory import get_memory
from audit_compiler.agent.context import AgentContext
from audit_compiler.agent.models import ToolResult


def find_related_entities(ctx: AgentContext, args: dict) -> ToolResult:
    """Return entities/events/evidence related to a given entity id, multi-hop."""

    entity_id = args.get("entity_id")
    if not entity_id:
        return ToolResult(
            tool_name="find_related_entities",
            ok=False,
            errors=("`entity_id` is required",),
        )
    hops = int(args.get("hops", 2))
    memory = get_memory()
    result = memory.related_entities(entity_id, hops=hops)
    notes = () if result["nodes"] or result["edges"] else ("no related entities found",)
    return ToolResult(
        tool_name="find_related_entities",
        ok=True,
        structured_result={**result, "entity_id": entity_id, "hops": hops},
        errors=notes,
    )


def find_similar_investigation_paths(ctx: AgentContext, args: dict) -> ToolResult:
    """Return previously recorded hypotheses in the same category, for pattern reuse."""

    category = args.get("category")
    if not category:
        return ToolResult(
            tool_name="find_similar_investigation_paths",
            ok=False,
            errors=("`category` is required",),
        )
    memory = get_memory()
    result = memory.similar_investigation_paths(category)
    notes = () if result["hypotheses"] else ("no similar investigation paths recorded yet",)
    return ToolResult(
        tool_name="find_similar_investigation_paths",
        ok=True,
        structured_result={**result, "category": category},
        errors=notes,
    )


def find_other_vendors_connected_to_user(ctx: AgentContext, args: dict) -> ToolResult:
    """Return other vendor entities reachable from a given user id, multi-hop."""

    user_id = args.get("user_id")
    if not user_id:
        return ToolResult(
            tool_name="find_other_vendors_connected_to_user",
            ok=False,
            errors=("`user_id` is required",),
        )
    hops = int(args.get("hops", 3))
    memory = get_memory()
    result = memory.vendors_connected_to_user(user_id, hops=hops)
    notes = () if result["vendors"] else ("no connected vendors found",)
    return ToolResult(
        tool_name="find_other_vendors_connected_to_user",
        ok=True,
        structured_result={**result, "user_id": user_id, "hops": hops},
        errors=notes,
    )


def retrieve_open_hypothesis_context(ctx: AgentContext, args: dict) -> ToolResult:
    """Return the recorded neighborhood (evidence, entities, events) of an open hypothesis."""

    hypothesis_id = args.get("hypothesis_id")
    if not hypothesis_id:
        return ToolResult(
            tool_name="retrieve_open_hypothesis_context",
            ok=False,
            errors=("`hypothesis_id` is required",),
        )
    memory = get_memory()
    result = memory.open_hypothesis_context(hypothesis_id)
    notes = (
        () if result["nodes"] or result["edges"] else ("no recorded context for this hypothesis",)
    )
    return ToolResult(
        tool_name="retrieve_open_hypothesis_context",
        ok=True,
        structured_result={**result, "hypothesis_id": hypothesis_id},
        errors=notes,
    )


COGNEE_TOOLS: dict[str, Any] = {
    "find_related_entities": find_related_entities,
    "find_similar_investigation_paths": find_similar_investigation_paths,
    "find_other_vendors_connected_to_user": find_other_vendors_connected_to_user,
    "retrieve_open_hypothesis_context": retrieve_open_hypothesis_context,
}
