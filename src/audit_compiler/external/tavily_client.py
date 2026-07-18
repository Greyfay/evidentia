"""Tavily-backed `ExternalVerifier`.

Only ever constructed by `get_verifier(enabled=True)` when `TAVILY_API_KEY` is
set; see `audit_compiler.external.interface` for the opt-in gating. Any
network, auth, or library error degrades to `available=False` rather than
raising into the pipeline.
"""

from __future__ import annotations

import os
from typing import Any

from audit_compiler.external.interface import ExternalCheck


class TavilyVerifier:
    """`ExternalVerifier` implementation backed by the Tavily search API."""

    provider = "tavily"

    def __init__(self, client: Any | None = None) -> None:
        if client is not None:
            self._client = client
            return
        # Deferred import: `tavily-python` is an optional dependency.
        from tavily import TavilyClient

        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            raise RuntimeError("TAVILY_API_KEY is not set")
        self._client = TavilyClient(api_key=api_key)

    def verify_entity(self, name: str, context: str) -> ExternalCheck:
        query = f"{name} {context}".strip()
        try:
            response = self._client.search(query=query, max_results=5)
        except Exception as exc:  # noqa: BLE001 - any failure must degrade, never raise
            return ExternalCheck(
                available=False,
                provider=self.provider,
                query=query,
                error=f"{type(exc).__name__}: {exc}",
            )

        results = response.get("results", []) if isinstance(response, dict) else []
        sources = tuple(r.get("url", "") for r in results if isinstance(r, dict) and r.get("url"))
        name_lower = name.lower()
        verified = any(
            name_lower in f"{r.get('title', '')} {r.get('content', '')}".lower()
            for r in results
            if isinstance(r, dict)
        )
        summary = response.get("answer") if isinstance(response, dict) else None
        return ExternalCheck(
            available=True,
            provider=self.provider,
            query=query,
            verified=verified,
            summary=summary,
            sources=sources,
        )
