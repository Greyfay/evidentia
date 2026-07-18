"""Tests for the investigation API + ZIP upload (store, investigations router, app wiring)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audit_compiler.agent import store as store_module
from audit_compiler.api.app import app


@pytest.fixture(autouse=True)
def _clean_store():
    """Every test starts from an empty engagement/investigation store."""

    store_module.reset_store()
    yield
    store_module.reset_store()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


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


def test_upload_zip_happy_path(client: TestClient) -> None:
    response = client.post(
        "/engagements/upload",
        files={"file": ("dossier.zip", _minimal_dossier_zip(), "application/zip")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "engagement_id" in body and body["engagement_id"]
    assert "engagement" in body
    assert body["engagement"]["name"]


@pytest.mark.parametrize(
    "evil_name",
    ["../evil.txt", "/etc/passwd", "dossier/../../evil.txt"],
)
def test_upload_zip_path_traversal_rejected(client: TestClient, evil_name: str) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("dossier/invoices.csv", "invoice_id\nINV-1\n")
        zf.writestr(evil_name, "pwned")
    response = client.post(
        "/engagements/upload",
        files={"file": ("evil.zip", buf.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    # Nothing should have leaked outside any temp dir this test can observe.
    assert not Path("/tmp/evil.txt").exists()
    assert not Path("evil.txt").exists()


def test_unknown_investigation_id_404(client: TestClient) -> None:
    response = client.get("/investigations/does-not-exist")
    assert response.status_code == 404
    response = client.post("/investigations/does-not-exist/run-next")
    assert response.status_code == 404
    response = client.get("/investigations/does-not-exist/timeline")
    assert response.status_code == 404


def test_full_lifecycle(client: TestClient) -> None:
    upload = client.post(
        "/engagements/upload",
        files={"file": ("dossier.zip", _minimal_dossier_zip(), "application/zip")},
    )
    assert upload.status_code == 200, upload.text
    engagement_id = upload.json()["engagement_id"]

    created = client.post(
        "/investigations",
        json={"engagement_id": engagement_id, "objective": "look for vendor fraud"},
    )
    assert created.status_code == 200, created.text
    inv = created.json()
    investigation_id = inv["investigation_id"]

    listing = client.get("/investigations")
    assert listing.status_code == 200
    assert any(i["investigation_id"] == investigation_id for i in listing.json()["investigations"])

    ran = client.post(f"/investigations/{investigation_id}/run")
    assert ran.status_code == 200, ran.text
    ran_inv = ran.json()
    assert ran_inv["status"] in {
        "completed", "stopped", "active", "awaiting_auditor", "submitted", "dismissed",
    }

    fetched = client.get(f"/investigations/{investigation_id}")
    assert fetched.status_code == 200
    fetched_inv = fetched.json()
    assert fetched_inv["investigation_id"] == investigation_id

    timeline = client.get(f"/investigations/{investigation_id}/timeline")
    assert timeline.status_code == 200
    assert len(timeline.json()["timeline"]) > 0

    graph = client.get(f"/investigations/{investigation_id}/graph")
    assert graph.status_code == 200
    graph_body = graph.json()
    assert "nodes" in graph_body and "edges" in graph_body

    if fetched_inv["hypotheses"]:
        hypothesis_id = fetched_inv["hypotheses"][0]["hypothesis_id"]
        dismissed = client.post(
            f"/investigations/{investigation_id}/hypotheses/{hypothesis_id}/dismiss"
        )
        assert dismissed.status_code == 200, dismissed.text
        dismissed_inv = dismissed.json()
        hyp = next(h for h in dismissed_inv["hypotheses"] if h["hypothesis_id"] == hypothesis_id)
        assert hyp["status"] == "dismissed"

        continued = client.post(
            f"/investigations/{investigation_id}/hypotheses/{hypothesis_id}/continue"
        )
        assert continued.status_code == 200
        hyp = next(
            h for h in continued.json()["hypotheses"] if h["hypothesis_id"] == hypothesis_id
        )
        assert hyp["status"] == "active"

        challenged = client.post(
            f"/investigations/{investigation_id}/hypotheses/{hypothesis_id}/challenge",
            json={"note": "please provide more evidence"},
        )
        assert challenged.status_code == 200
        challenged_inv = challenged.json()
        assert "please provide more evidence" in challenged_inv["questions_for_auditor"]

    message = client.post(
        f"/investigations/{investigation_id}/messages", json={"message": "any update?"}
    )
    assert message.status_code == 200
    assert "any update?" in message.json()["questions_for_auditor"]


def test_sample_dossier_compiles_and_runs(client: TestClient, sample_dossier: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path in sample_dossier.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(sample_dossier.parent)))
    upload = client.post(
        "/engagements/upload",
        files={"file": ("sample.zip", buf.getvalue(), "application/zip")},
    )
    assert upload.status_code == 200, upload.text
    engagement_id = upload.json()["engagement_id"]

    created = client.post(
        "/investigations",
        json={"engagement_id": engagement_id, "objective": "audit vendor payments"},
    )
    assert created.status_code == 200, created.text
    investigation_id = created.json()["investigation_id"]

    ran = client.post(f"/investigations/{investigation_id}/run")
    assert ran.status_code == 200, ran.text

    timeline = client.get(f"/investigations/{investigation_id}/timeline")
    assert len(timeline.json()["timeline"]) > 0
