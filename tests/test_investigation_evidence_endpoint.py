"""Tests for the investigation-scoped evidence resolver.

``GET /investigations/{investigation_id}/evidence/{evidence_id}`` resolves one of an
investigation's ``ev_...`` ids to its exact source pointer and raw snippet, through the
engagement's evidence registry (not any fixture). The pre-existing bundle-scoped
``GET /evidence/{evidence_id}`` must keep working.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from audit_compiler.agent import store as store_module
from audit_compiler.agent import tool_registry
from audit_compiler.agent.context import AgentContext
from audit_compiler.agent.models import Investigation
from audit_compiler.agent.store import get_store
from audit_compiler.api.app import app

app_module = importlib.import_module("audit_compiler.api.app")
pytestmark = pytest.mark.anyio


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


def _seed_investigation(tmp_path: Path) -> tuple[str, str]:
    """Compile a tiny real dossier, emit a genuine evidence id via a tool, and open a
    compiled investigation that holds it. Returns ``(investigation_id, evidence_id)``."""

    (tmp_path / "invoices.csv").write_text(
        "invoice_id,vendor_id,amount,date\nINV-1,VEND-1,100.00,2024-01-05\n"
    )
    (tmp_path / "vendors.csv").write_text(
        "vendor_id,name,created_by,approved_by\nVEND-1,Acme,alice,alice\n"
    )
    ctx = AgentContext.from_dossier_path(tmp_path)
    result = tool_registry.run_tool(ctx, "search_evidence", {"query": "VEND-1"})
    assert result.ok and result.evidence_ids, "expected the tool to cite a real evidence id"
    evidence_id = result.evidence_ids[0]

    store = get_store()
    engagement_id = store.add_engagement(
        "eng_test", ctx, {"engagement": {"engagement_id": "eng_test"}, "cases": []}
    )
    now = datetime.now(UTC)
    inv = Investigation(
        engagement_id=engagement_id,
        objective="audit vendor payments",
        evidence_ids=[evidence_id],
        created_at=now,
        updated_at=now,
    )
    store.save(inv)
    return str(inv.investigation_id), evidence_id


async def test_resolves_investigation_evidence_to_exact_source(
    client: AsyncClient, tmp_path: Path
) -> None:
    investigation_id, evidence_id = _seed_investigation(tmp_path)

    response = await client.get(
        f"/investigations/{investigation_id}/evidence/{evidence_id}"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "evidence_id", "kind", "source", "snippet",
        "source_path", "locator", "file_sha256",
    }
    assert body["evidence_id"] == evidence_id
    assert body["kind"] == "csv_row"
    assert body["snippet"] == "VEND-1"  # the exact raw source value
    assert "invoices.csv" in body["source"]
    assert "row" in body["source"]
    # The new fields let the client pick a viewer and deep-link the cited coordinate.
    assert body["source_path"] == "invoices.csv"
    assert body["locator"]["row"] == 2  # INV-1 is the second physical line
    assert len(body["file_sha256"]) == 64  # sha-256 hex digest


async def test_unknown_evidence_id_is_404(client: AsyncClient, tmp_path: Path) -> None:
    investigation_id, _ = _seed_investigation(tmp_path)
    response = await client.get(
        f"/investigations/{investigation_id}/evidence/ev_deadbeefdeadbeef"
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "evidence not found for this investigation"}


async def test_unknown_investigation_is_404(client: AsyncClient) -> None:
    response = await client.get("/investigations/nope/evidence/ev_0000000000000000")
    assert response.status_code == 404
    assert response.json() == {"detail": "investigation not found"}


async def test_source_file_streams_the_original_upload(
    client: AsyncClient, tmp_path: Path
) -> None:
    """The source-file route serves the exact original file the auditor uploaded, byte for
    byte, inline so the browser can render it in place."""

    investigation_id, evidence_id = _seed_investigation(tmp_path)
    response = await client.get(
        f"/investigations/{investigation_id}/evidence/{evidence_id}/source-file"
    )
    assert response.status_code == 200, response.text
    assert response.content == (tmp_path / "invoices.csv").read_bytes()
    assert response.headers["content-type"].startswith("text/csv")
    assert "inline" in response.headers.get("content-disposition", "")


async def test_source_file_unknown_evidence_is_404(
    client: AsyncClient, tmp_path: Path
) -> None:
    investigation_id, _ = _seed_investigation(tmp_path)
    response = await client.get(
        f"/investigations/{investigation_id}/evidence/ev_deadbeefdeadbeef/source-file"
    )
    assert response.status_code == 404


async def test_source_file_unknown_investigation_is_404(client: AsyncClient) -> None:
    response = await client.get(
        "/investigations/nope/evidence/ev_0000000000000000/source-file"
    )
    assert response.status_code == 404


def test_serve_source_file_rejects_traversal(tmp_path: Path) -> None:
    """A source_path that resolves outside the dossier root is refused, never served."""

    from fastapi import HTTPException

    from audit_compiler.api.investigations import _serve_source_file

    (tmp_path / "secret.txt").write_text("do not serve me")
    root = tmp_path / "dossier"
    root.mkdir()
    with pytest.raises(HTTPException) as exc:
        _serve_source_file(root, "../secret.txt")
    assert exc.value.status_code == 404


def test_serve_source_file_missing_file_is_404(tmp_path: Path) -> None:
    from fastapi import HTTPException

    from audit_compiler.api.investigations import _serve_source_file

    with pytest.raises(HTTPException) as exc:
        _serve_source_file(tmp_path, "nope.csv")
    assert exc.value.status_code == 404


async def test_bundle_scoped_evidence_route_still_works(client: AsyncClient) -> None:
    """The new investigation-scoped route must not shadow the original bundle route."""

    app_module._STATE["bundle"] = {
        "engagement": {"engagement_id": "eng", "run_id": "run"},
        "cases": [
            {
                "case_id": "case-1",
                "evidence_chain": [
                    {"evidence": [{"evidence_id": "EV-1", "raw_value": "42"}]}
                ],
                "calculation": {"evidence": []},
                "counter_tests": [],
            }
        ],
    }
    response = await client.get("/evidence/EV-1")
    assert response.status_code == 200, response.text
    assert response.json()["evidence_id"] == "EV-1"
