"""Tests for the investigation API + ZIP upload (store, investigations router, app wiring)."""

from __future__ import annotations

import importlib
import io
import zipfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from audit_compiler.agent import store as store_module
from audit_compiler.api.app import app

app_module = importlib.import_module("audit_compiler.api.app")
pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _clean_store():
    """Every test starts from an empty engagement/investigation store."""

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


def _zip_bytes(files: dict[str, str], *, top_folder: str | None = "dossier") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            path = f"{top_folder}/{name}" if top_folder else name
            zf.writestr(path, content)
    return buf.getvalue()


def _minimal_dossier_zip() -> bytes:
    invoices_csv = (
        "invoice_id,vendor_id,amount,date\n"
        "INV-1,VEND-1,100.00,2024-01-05\n"
        "INV-2,VEND-2,250.00,2024-01-06\n"
    )
    vendors_csv = (
        "vendor_id,name,created_by,approved_by\n"
        "VEND-1,Acme,alice,alice\n"
        "VEND-2,Beta,bob,carol\n"
    )
    return _zip_bytes({"invoices.csv": invoices_csv, "vendors.csv": vendors_csv})


async def test_upload_zip_happy_path(client: AsyncClient) -> None:
    response = await client.post(
        "/engagements/upload",
        files={"file": ("dossier.zip", _minimal_dossier_zip(), "application/zip")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "engagement_id" in body and body["engagement_id"]
    assert "engagement" in body
    assert body["engagement"]["name"]


async def test_upload_control_allowlist_is_visible(client: AsyncClient) -> None:
    response = await client.post(
        "/engagements/upload",
        files={"file": ("dossier.zip", _minimal_dossier_zip(), "application/zip")},
        data={"control_ids": "split_payment"},
    )
    assert response.status_code == 200, response.text
    controls = response.json()["engagement"]["controls"]
    assert controls["selected"] == ["split_payment"]
    assert controls["executed"] == ["split_payment"]
    assert controls["failed"] == []
    assert set(controls["skipped"]) == {
        "vendor_sod",
        "capitalisation",
        "cutoff",
        "anomaly_discovery",
    }
    assert "control skipped by explicit allowlist: anomaly_discovery" in controls["warnings"]


async def test_upload_rejects_unknown_control_id(client: AsyncClient) -> None:
    response = await client.post(
        "/engagements/upload",
        files={"file": ("dossier.zip", _minimal_dossier_zip(), "application/zip")},
        data={"control_ids": "split_payment,not_a_control"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "unknown control ID(s): not_a_control"


_INVOICES_CSV = (
    "invoice_id,vendor_id,amount,date\n"
    "INV-1,VEND-1,100.00,2024-01-05\n"
    "INV-2,VEND-2,250.00,2024-01-06\n"
)
_VENDORS_CSV = (
    "vendor_id,name,created_by,approved_by\n"
    "VEND-1,Acme,alice,alice\n"
    "VEND-2,Beta,bob,carol\n"
)


async def test_upload_single_csv_file(client: AsyncClient) -> None:
    response = await client.post(
        "/engagements/upload",
        files={"files": ("invoices.csv", _INVOICES_CSV, "text/csv")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engagement_id"]
    assert body["engagement"]["counts"]["source_files"] == 1


async def test_upload_multiple_individual_files(client: AsyncClient) -> None:
    response = await client.post(
        "/engagements/upload",
        files=[
            ("files", ("invoices.csv", _INVOICES_CSV, "text/csv")),
            ("files", ("vendors.csv", _VENDORS_CSV, "text/csv")),
        ],
    )
    assert response.status_code == 200, response.text
    assert response.json()["engagement"]["counts"]["source_files"] == 2


async def test_upload_rejects_unsupported_file_type(client: AsyncClient) -> None:
    response = await client.post(
        "/engagements/upload",
        files={"files": ("notes.exe", b"\x00\x01", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "unsupported file type" in response.json()["detail"]


async def test_upload_rejects_zip_mixed_with_other_files(client: AsyncClient) -> None:
    response = await client.post(
        "/engagements/upload",
        files=[
            ("files", ("dossier.zip", _minimal_dossier_zip(), "application/zip")),
            ("files", ("invoices.csv", _INVOICES_CSV, "text/csv")),
        ],
    )
    assert response.status_code == 400
    assert "on its own" in response.json()["detail"]


async def test_upload_rejects_empty_request(client: AsyncClient) -> None:
    response = await client.post("/engagements/upload", data={"note": "no file here"})
    assert response.status_code == 400
    assert "no file uploaded" in response.json()["detail"]


async def test_uploads_are_isolated_and_each_source_is_parsed_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import audit_compiler.ir.dossier as dossier_module

    calls = 0
    original = dossier_module.load_dossier

    def counted(path: Path, **kwargs):
        nonlocal calls
        calls += 1
        return original(path, **kwargs)

    monkeypatch.setattr(dossier_module, "load_dossier", counted)
    first = await client.post(
        "/engagements/upload",
        files={"file": ("first.zip", _minimal_dossier_zip(), "application/zip")},
    )
    second = await client.post(
        "/engagements/upload",
        files={"file": ("second.zip", _minimal_dossier_zip(), "application/zip")},
    )
    assert first.status_code == second.status_code == 200
    first_id = first.json()["engagement_id"]
    second_id = second.json()["engagement_id"]
    assert first_id != second_id
    assert calls == 2
    store = store_module.get_store()
    assert store.get_context(first_id) is not store.get_context(second_id)
    assert first.json()["engagement"]["run_id"] != second.json()["engagement"]["run_id"]


async def test_review_serialization_and_missing_case_error(client: AsyncClient) -> None:
    app_module._STATE["bundle"] = {
        "engagement": {"engagement_id": "eng", "run_id": "run"},
        "cases": [{"case_id": "case-1", "reviewer_decision": None}],
    }
    reviewed = await client.post(
        "/cases/case-1/review",
        json={"decision": "request_evidence", "note": "obtain invoice"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["reviewer_decision"] == {
        "decision": "request_evidence",
        "note": "obtain invoice",
    }
    missing = await client.post("/cases/missing/review", json={"decision": "dismiss"})
    assert missing.status_code == 404
    assert missing.json() == {"detail": "case not found"}


@pytest.mark.parametrize(
    "evil_name",
    ["../evil.txt", "/etc/passwd", "dossier/../../evil.txt"],
)
async def test_upload_zip_path_traversal_rejected(
    client: AsyncClient, evil_name: str
) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("dossier/invoices.csv", "invoice_id\nINV-1\n")
        zf.writestr(evil_name, "pwned")
    response = await client.post(
        "/engagements/upload",
        files={"file": ("evil.zip", buf.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    # Nothing should have leaked outside any temp dir this test can observe.
    assert not Path("/tmp/evil.txt").exists()
    assert not Path("evil.txt").exists()


async def test_unknown_investigation_id_404(client: AsyncClient) -> None:
    response = await client.get("/investigations/does-not-exist")
    assert response.status_code == 404
    response = await client.post("/investigations/does-not-exist/run-next")
    assert response.status_code == 404
    response = await client.get("/investigations/does-not-exist/timeline")
    assert response.status_code == 404


async def test_full_lifecycle(client: AsyncClient) -> None:
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
    inv = created.json()
    investigation_id = inv["investigation_id"]

    listing = await client.get("/investigations")
    assert listing.status_code == 200
    assert any(i["investigation_id"] == investigation_id for i in listing.json()["investigations"])

    ran = await client.post(f"/investigations/{investigation_id}/run")
    assert ran.status_code == 200, ran.text
    ran_inv = ran.json()
    assert ran_inv["status"] in {
        "completed", "stopped", "active", "awaiting_auditor", "submitted", "dismissed",
    }

    fetched = await client.get(f"/investigations/{investigation_id}")
    assert fetched.status_code == 200
    fetched_inv = fetched.json()
    assert fetched_inv["investigation_id"] == investigation_id

    timeline = await client.get(f"/investigations/{investigation_id}/timeline")
    assert timeline.status_code == 200
    assert len(timeline.json()["timeline"]) > 0

    graph = await client.get(f"/investigations/{investigation_id}/graph")
    assert graph.status_code == 200
    graph_body = graph.json()
    assert "nodes" in graph_body and "edges" in graph_body

    if fetched_inv["hypotheses"]:
        hypothesis_id = fetched_inv["hypotheses"][0]["hypothesis_id"]
        dismissed = await client.post(
            f"/investigations/{investigation_id}/hypotheses/{hypothesis_id}/dismiss"
        )
        assert dismissed.status_code == 200, dismissed.text
        dismissed_inv = dismissed.json()
        hyp = next(h for h in dismissed_inv["hypotheses"] if h["hypothesis_id"] == hypothesis_id)
        assert hyp["status"] == "dismissed"

        continued = await client.post(
            f"/investigations/{investigation_id}/hypotheses/{hypothesis_id}/continue"
        )
        assert continued.status_code == 200
        hyp = next(
            h for h in continued.json()["hypotheses"] if h["hypothesis_id"] == hypothesis_id
        )
        assert hyp["status"] == "active"

        challenged = await client.post(
            f"/investigations/{investigation_id}/hypotheses/{hypothesis_id}/challenge",
            json={"note": "please provide more evidence"},
        )
        assert challenged.status_code == 200
        challenged_inv = challenged.json()
        assert "please provide more evidence" in challenged_inv["questions_for_auditor"]

    message = await client.post(
        f"/investigations/{investigation_id}/messages", json={"message": "any update?"}
    )
    assert message.status_code == 200
    assert "any update?" in message.json()["questions_for_auditor"]


async def test_sample_dossier_compiles_and_runs(
    client: AsyncClient, sample_dossier: Path
) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path in sample_dossier.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(sample_dossier.parent)))
    upload = await client.post(
        "/engagements/upload",
        files={"file": ("sample.zip", buf.getvalue(), "application/zip")},
        data={"control_ids": "split_payment"},
    )
    assert upload.status_code == 200, upload.text
    controls = upload.json()["engagement"]["controls"]
    assert controls["selected"] == ["split_payment"]
    assert controls["executed"] == ["split_payment"]
    assert controls["failed"] == []
    assert "anomaly_discovery" in controls["skipped"]
    assert any("anomaly_discovery" in warning for warning in controls["warnings"])
    engagement_id = upload.json()["engagement_id"]

    created = await client.post(
        "/investigations",
        json={"engagement_id": engagement_id, "objective": "audit vendor payments"},
    )
    assert created.status_code == 200, created.text
    investigation_id = created.json()["investigation_id"]

    ran = await client.post(f"/investigations/{investigation_id}/run")
    assert ran.status_code == 200, ran.text

    timeline = await client.get(f"/investigations/{investigation_id}/timeline")
    assert len(timeline.json()["timeline"]) > 0
