from __future__ import annotations

import importlib
import io
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from audit_compiler.agent import store as store_module
from audit_compiler.api.app import app

app_module = importlib.import_module("audit_compiler.api.app")
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def clean_api_state():
    store_module.reset_store()
    app_module._STATE["bundle"] = None
    yield
    store_module.reset_store()
    app_module._STATE["bundle"] = None


def dossier_zip() -> bytes:
    payments = (
        "documentno,paymentref,amount,postingdate,postingtype,narrative\n"
        "PAY-1,BATCH-42,6000,2026-01-15,payment,first leg\n"
        "PAY-2,BATCH-42,5000,2026-01-15,payment,second leg\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("dossier/payments.csv", payments)
    return buffer.getvalue()


async def test_browser_zip_upload_compile_list_and_open_evidence() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        upload = await client.post(
            "/engagements/upload",
            files={"file": ("dossier.zip", dossier_zip(), "application/zip")},
            data={"control_ids": "split_payment"},
        )
        assert upload.status_code == 200, upload.text
        investigation_id = upload.json()["investigation_id"]

        compiled = await client.post(
            "/engagements/compile",
            json={
                "investigation_id": investigation_id,
                "control_ids": ["split_payment"],
            },
        )
        assert compiled.status_code == 200, compiled.text
        assert compiled.json()["controls"]["selected"] == ["split_payment"]

        listed = await client.get("/cases")
        assert listed.status_code == 200, listed.text
        case = listed.json()["cases"][0]
        evidence_id = case["evidence_chain"][0]["evidence"][0]["evidence_id"]

        evidence = await client.get(f"/evidence/{evidence_id}")
        assert evidence.status_code == 200, evidence.text
        assert evidence.json()["evidence_id"] == evidence_id
