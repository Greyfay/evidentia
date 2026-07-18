from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest

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
