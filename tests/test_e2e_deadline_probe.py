from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI

SCRIPT = Path(__file__).parents[1] / "scripts" / "e2e_deadline_probe.py"
SPEC = importlib.util.spec_from_file_location("e2e_deadline_probe", SCRIPT)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def succeeds(_context, progress):
    progress("WORK_DONE", value=1)
    return {"value": 1}


def fails(_context, _progress):
    raise ValueError("synthetic failure")


def hangs(_context, progress):
    progress("CONTROL_START", control_id="slow_control")
    time.sleep(10)
    return {}


def test_successful_stage_execution():
    result = probe.execute_stage(probe.Stage("synthetic", "ok", 1, succeeds), {})
    assert result["value"] == 1
    assert result["elapsed_seconds"] < 1


def test_exception_reporting():
    with pytest.raises(probe.ProbeFailure) as caught:
        probe.execute_stage(probe.Stage("synthetic", "bad", 1, fails), {})
    assert caught.value.report["status"] == "failure"
    assert caught.value.report["exception"]["type"] == "ValueError"
    assert "synthetic failure" in caught.value.report["exception"]["traceback"]


def test_timeout_terminates_and_requests_stack_dump():
    with pytest.raises(probe.ProbeFailure) as caught:
        probe.execute_stage(
            probe.Stage("registered_control", "slow_control", 0.1, hangs),
            {"controls": ["slow_control"], "dossier": "/tmp/dossier"},
        )
    report = caught.value.report
    assert report["status"] == "timeout"
    assert report["stack_dump_emitted"] is True
    assert report["component"] == "slow_control"
    assert report["last_progress_event"]["control_id"] == "slow_control"


def test_fail_fast_prevents_later_stage(tmp_path):
    marker = tmp_path / "later-ran"

    def later(_context, _progress):
        marker.touch()
        return {}

    stages = [probe.Stage("first", "first", 1, fails), probe.Stage("later", "later", 1, later)]
    with pytest.raises(probe.ProbeFailure):
        for stage in stages:
            probe.execute_stage(stage, {})
    assert not marker.exists()


def test_api_lifecycle_keeps_state_in_one_app_process(tmp_path):
    dossier = tmp_path / "dossier"
    dossier.mkdir()
    (dossier / "invoices.csv").write_text("invoice_id,amount\nINV-1,42\n")
    app = FastAPI()
    state = {"uploaded": False, "reviewed": False}
    case = {
        "case_id": "case-from-list-response",
        "evidence_chain": [
            {"evidence": [{"evidence_id": "evidence-from-case-response"}]}
        ],
        "calculation": {"evidence": []},
        "counter_tests": [],
    }

    @app.post("/engagements/upload")
    async def upload():
        state["uploaded"] = True
        return {"engagement_id": "engagement-from-upload-response"}

    @app.post("/investigations")
    async def create_investigation():
        assert state["uploaded"]
        return {"investigation_id": "investigation-from-http-response"}

    @app.get("/cases")
    async def list_cases():
        assert state["uploaded"]
        return {"cases": [case]}

    @app.get("/cases/{case_id}")
    async def get_case(case_id: str):
        assert state["uploaded"]
        assert case_id == case["case_id"]
        return case

    @app.get("/evidence/{evidence_id}")
    async def get_evidence(evidence_id: str):
        assert state["uploaded"]
        return {"evidence_id": evidence_id}

    @app.post("/cases/{case_id}/review")
    async def review(case_id: str):
        assert state["uploaded"]
        assert case_id == case["case_id"]
        state["reviewed"] = True
        return case

    events = []

    def progress(event, **fields):
        events.append((event, fields))

    result = probe.asyncio.run(
        probe._run_api_lifecycle(
            {"dossier": str(dossier), "controls": ["split_payment"]}, progress, app
        )
    )

    assert state == {"uploaded": True, "reviewed": True}
    assert result["investigation_id"] == "investigation-from-http-response"
    assert result["case_id"] == "case-from-list-response"
    assert [event for event, _fields in events] == [
        "API_UPLOAD_START",
        "API_UPLOAD_END",
        "API_LIST_START",
        "API_LIST_END",
        "API_GET_CASE_START",
        "API_GET_CASE_END",
        "API_EVIDENCE_START",
        "API_EVIDENCE_END",
        "API_REVIEW_START",
        "API_REVIEW_END",
    ]
