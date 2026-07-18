#!/usr/bin/env python3
"""Fail-fast, per-feature deadline probe for the complete Evidentia journey."""

from __future__ import annotations

import argparse
import asyncio
import faulthandler
import io
import json
import multiprocessing as mp
import os
import pickle
import signal
import sys
import tempfile
import time
import traceback
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUTS = {
    "validate_dossier_path": 2.0,
    "inventory_and_hash": 5.0,
    "native_parse_and_canonical_compile": 20.0,
    "duckdb_persistence": 10.0,
    "control": 8.0,
    "admission_and_case_building": 5.0,
    "api_lifecycle": 30.0,
}

API_SUBSTEP_TIMEOUT_SECONDS = 5.0


def _json_default(value: object) -> str:
    return str(value)


def emit(event: str, **fields: object) -> dict[str, object]:
    payload = {"event": event, "at": time.time(), **fields}
    print(json.dumps(payload, default=_json_default, sort_keys=True), flush=True)
    return payload


@dataclass(frozen=True)
class Stage:
    name: str
    component: str
    budget: float
    target: Callable[[dict[str, Any], Callable[..., dict[str, object]]], dict[str, Any]]


def _child_main(stage: Stage, context: dict[str, Any], connection: Any) -> None:
    faulthandler.enable(all_threads=True)
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)

    def progress(event: str, **fields: object) -> dict[str, object]:
        payload = emit(event, stage=stage.name, component=stage.component, **fields)
        connection.send(("progress", payload))
        return payload

    started = time.monotonic()
    try:
        progress("STAGE_START", child_pid=os.getpid(), budget_seconds=stage.budget)
        result = stage.target(context, progress) or {}
        elapsed = time.monotonic() - started
        progress("STAGE_END", elapsed_seconds=elapsed, status="success")
        connection.send(("result", result))
    except BaseException as exc:
        elapsed = time.monotonic() - started
        detail = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        progress("STAGE_FAILURE", elapsed_seconds=elapsed, exception=detail)
        connection.send(("failure", detail))
    finally:
        connection.close()


def execute_stage(stage: Stage, context: dict[str, Any]) -> dict[str, Any]:
    """Execute one stage in a child and raise with structured diagnostic data."""
    parent, child = mp.get_context("fork").Pipe(duplex=False)
    process = mp.get_context("fork").Process(
        target=_child_main, args=(stage, context, child), name=f"probe:{stage.component}"
    )
    started = time.monotonic()
    process.start()
    child.close()
    last_progress: dict[str, object] | None = None
    result: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    deadline = started + stage.budget
    while process.is_alive() and time.monotonic() < deadline:
        if parent.poll(min(0.05, max(0.0, deadline - time.monotonic()))):
            try:
                kind, payload = parent.recv()
            except EOFError:
                break
            if kind == "progress":
                last_progress = payload
            elif kind == "result":
                result = payload
            else:
                failure = payload
    elapsed = time.monotonic() - started
    if process.is_alive() and time.monotonic() < deadline:
        process.join(deadline - time.monotonic())
        elapsed = time.monotonic() - started
    if process.is_alive():
        stack_requested = False
        if hasattr(signal, "SIGUSR1"):
            os.kill(process.pid, signal.SIGUSR1)
            stack_requested = True
            process.join(0.25)
        if process.is_alive():
            process.terminate()
        process.join(1.0)
        report = {
            "status": "timeout",
            "stage": stage.name,
            "component": stage.component,
            "budget_seconds": stage.budget,
            "elapsed_seconds": elapsed,
            "last_progress_event": last_progress,
            "child_pid": process.pid,
            "stack_dump_emitted": stack_requested,
            "suggested_next_command": _suggested_command(context, stage.component),
        }
        emit("PROBE_FAILURE", **report)
        raise ProbeFailure(report)
    process.join()
    while parent.poll():
        try:
            kind, payload = parent.recv()
        except EOFError:
            break
        if kind == "progress":
            last_progress = payload
        elif kind == "result":
            result = payload
        else:
            failure = payload
    parent.close()
    if failure is not None or process.exitcode != 0 or result is None:
        report = {
            "status": "failure",
            "stage": stage.name,
            "component": stage.component,
            "budget_seconds": stage.budget,
            "elapsed_seconds": elapsed,
            "last_progress_event": last_progress,
            "child_pid": process.pid,
            "exception": failure or {"message": f"child exited {process.exitcode}"},
            "suggested_next_command": _suggested_command(context, stage.component),
        }
        emit("PROBE_FAILURE", **report)
        raise ProbeFailure(report)
    result["elapsed_seconds"] = elapsed
    return result


class ProbeFailure(RuntimeError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(json.dumps(report, default=_json_default))


def _suggested_command(context: dict[str, Any], component: str) -> str:
    controls = context.get("controls") or []
    control_arg = f" --controls {component}" if component in controls else ""
    return (
        f"EVIDENTIA_SAMPLE_DOSSIER={context.get('dossier', '')!s} "
        f"{sys.executable} scripts/e2e_deadline_probe.py --verbose{control_arg}"
    )


def validate_path(ctx: dict[str, Any], progress: Callable[..., Any]) -> dict[str, Any]:
    path = Path(ctx["dossier"]).expanduser().resolve()
    progress("PATH_RESOLVED", path=str(path))
    if not path.is_dir():
        raise NotADirectoryError(f"dossier path is not a directory: {path}")
    return {"dossier": str(path)}


def inventory(ctx: dict[str, Any], progress: Callable[..., Any]) -> dict[str, Any]:
    from audit_compiler.inventory import inventory_dossier

    manifest = inventory_dossier(Path(ctx["dossier"]))
    progress("INVENTORY_COMPLETE", file_count=len(manifest.files))
    return {"inventory_count": len(manifest.files)}


def native_compile(ctx: dict[str, Any], progress: Callable[..., Any]) -> dict[str, Any]:
    from audit_compiler.ir.canonical import map_canonical_events
    from audit_compiler.ir.dossier import load_dossier

    dossier = load_dossier(Path(ctx["dossier"]))
    progress("NATIVE_PARSE_COMPLETE", table_count=len(dossier.tables))
    events = map_canonical_events(dossier, engagement_id=ctx["engagement_id"], run_id=ctx["run_id"])
    progress("CANONICAL_COMPILE_COMPLETE", event_count=len(events))
    with Path(ctx["parsed_artifact"]).open("wb") as handle:
        pickle.dump((dossier, events), handle)
    return {
        "table_count": len(dossier.tables),
        "event_count": len(events),
        "subject_count": len({table.name for table in dossier.tables}),
    }


def persist_duckdb(ctx: dict[str, Any], progress: Callable[..., Any]) -> dict[str, Any]:
    from audit_compiler.duckdb_store import DuckDBAuditStore

    with Path(ctx["parsed_artifact"]).open("rb") as handle:
        dossier, events = pickle.load(handle)  # noqa: S301 - private trusted temp artifact
    store = DuckDBAuditStore(Path(ctx["database"]))
    store.persist_dossier(ctx["engagement_id"], ctx["run_id"], dossier, events=events)
    loaded = store.load_dossier(ctx["engagement_id"], ctx["run_id"])
    progress("DUCKDB_ROUNDTRIP_COMPLETE", table_count=len(loaded.tables))
    return {"persisted_table_count": len(loaded.tables)}


def run_control(ctx: dict[str, Any], progress: Callable[..., Any]) -> dict[str, Any]:
    from audit_compiler.controls.base import ControlContext
    from audit_compiler.controls.registry import default_controls
    from audit_compiler.duckdb_store import DuckDBAuditStore
    from audit_compiler.ir.roles import using_locale

    control_id = ctx["current_control"]
    control = next((item for item in default_controls() if item.id == control_id), None)
    if control is None:
        raise ValueError(f"registered control disappeared: {control_id}")
    dossier = DuckDBAuditStore(Path(ctx["database"])).load_dossier(
        ctx["engagement_id"], ctx["run_id"]
    )
    subject_count = len({table.name for table in dossier.tables})
    event_count = sum(len(table.rows) for table in dossier.tables)
    started = time.monotonic()
    progress(
        "CONTROL_START", control_id=control_id, subject_count=subject_count, event_count=event_count
    )
    try:
        with using_locale(dossier.locale.value):
            outcomes = tuple(control.run(ControlContext(dossier=dossier, params={})))
    except BaseException as exc:
        progress(
            "CONTROL_END",
            control_id=control_id,
            subject_count=subject_count,
            event_count=event_count,
            elapsed_seconds=time.monotonic() - started,
            outcome_count=0,
            exception={"type": type(exc).__name__, "message": str(exc)},
        )
        raise
    progress(
        "CONTROL_END",
        control_id=control_id,
        subject_count=subject_count,
        event_count=event_count,
        elapsed_seconds=time.monotonic() - started,
        outcome_count=len(outcomes),
        exception=None,
    )
    artifact = Path(ctx["workspace"]) / f"control-{control_id}.pickle"
    with artifact.open("wb") as handle:
        pickle.dump(outcomes, handle)
    return {"control_id": control_id, "outcome_count": len(outcomes), "artifact": str(artifact)}


def admission_cases(ctx: dict[str, Any], progress: Callable[..., Any]) -> dict[str, Any]:
    from audit_compiler.admission import admit
    from audit_compiler.casebuilder import case_dict

    cases: list[dict[str, Any]] = []
    for control_id in ctx["controls"]:
        with (Path(ctx["workspace"]) / f"control-{control_id}.pickle").open("rb") as handle:
            outcomes = pickle.load(handle)  # noqa: S301
        for outcome in outcomes:
            cases.append(
                case_dict(
                    outcome,
                    admit(outcome),
                    engagement_id=ctx["engagement_id"],
                    run_id=ctx["run_id"],
                )
            )
    Path(ctx["cases_artifact"]).write_text(
        json.dumps(cases, default=_json_default), encoding="utf-8"
    )
    verdicts = Counter(case["verdict"] for case in cases)
    progress("ADMISSION_COMPLETE", case_count=len(cases), verdict_counts=dict(verdicts))
    return {"cases_produced": len(cases), "verdict_counts": dict(verdicts)}


def _zip_dossier(path: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in path.rglob("*"):
            if source.is_file() and ".admissible" not in source.parts:
                archive.write(source, arcname=str(Path(path.name) / source.relative_to(path)))
    return buffer.getvalue()


class ApiSubstepFailure(RuntimeError):
    """An HTTP lifecycle substep failed, with its complete response diagnostics."""

    def __init__(
        self, endpoint: str, status_code: int | None, response_body: str, elapsed: float
    ) -> None:
        self.endpoint = endpoint
        self.status_code = status_code
        self.response_body = response_body
        self.elapsed_seconds = elapsed
        super().__init__(
            f"endpoint={endpoint} status_code={status_code} "
            f"response_body={response_body!r} elapsed_seconds={elapsed:.6f}"
        )


async def _request(client: Any, method: str, endpoint: str, **kwargs: Any) -> Any:
    started = time.monotonic()
    try:
        response = await asyncio.wait_for(
            client.request(method, endpoint, **kwargs),
            timeout=API_SUBSTEP_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        elapsed = time.monotonic() - started
        raise ApiSubstepFailure(endpoint, None, "<request timed out>", elapsed) from exc
    except BaseException as exc:
        elapsed = time.monotonic() - started
        raise ApiSubstepFailure(endpoint, None, str(exc), elapsed) from exc
    elapsed = time.monotonic() - started
    if response.is_error:
        raise ApiSubstepFailure(endpoint, response.status_code, response.text, elapsed)
    response.extensions["probe_elapsed_seconds"] = elapsed
    return response


def _payload(response: Any, endpoint: str) -> dict[str, Any]:
    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("response payload is not an object")
        return payload
    except BaseException as exc:
        raise ApiSubstepFailure(
            endpoint,
            response.status_code,
            response.text,
            response.extensions.get("probe_elapsed_seconds", 0.0),
        ) from exc


def _case_evidence(case: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = [item for step in case.get("evidence_chain", []) for item in step["evidence"]]
    evidence.extend(case.get("calculation", {}).get("evidence", []))
    evidence.extend(
        item for counter_test in case.get("counter_tests", []) for item in counter_test["evidence"]
    )
    return evidence


async def _run_api_lifecycle(
    ctx: dict[str, Any], progress: Callable[..., Any], app: Any
) -> dict[str, Any]:
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://probe"
    ) as client:
        progress("API_UPLOAD_START", endpoint="/engagements/upload")
        upload = await _request(
            client,
            "POST",
            "/engagements/upload",
            files={
                "file": (
                    "dossier.zip",
                    _zip_dossier(Path(ctx["dossier"])),
                    "application/zip",
                )
            },
            data={"control_ids": ",".join(ctx["controls"])} if ctx["controls"] else {},
        )
        upload_body = _payload(upload, "/engagements/upload")
        try:
            engagement_id = upload_body["engagement_id"]
        except KeyError as exc:
            raise ApiSubstepFailure(
                "/engagements/upload", upload.status_code, upload.text,
                upload.extensions["probe_elapsed_seconds"],
            ) from exc
        created = await _request(
            client,
            "POST",
            "/investigations",
            json={"engagement_id": engagement_id, "objective": "deadline probe"},
        )
        created_body = _payload(created, "/investigations")
        try:
            investigation_id = created_body["investigation_id"]
        except KeyError as exc:
            raise ApiSubstepFailure(
                "/investigations", created.status_code, created.text,
                created.extensions["probe_elapsed_seconds"],
            ) from exc
        progress(
            "API_UPLOAD_END",
            endpoint="/engagements/upload",
            status_code=upload.status_code,
            investigation_id=investigation_id,
        )

        progress("API_LIST_START", endpoint="/cases")
        listed = await _request(client, "GET", "/cases")
        listed_body = _payload(listed, "/cases")
        try:
            cases = listed_body["cases"]
        except KeyError as exc:
            raise ApiSubstepFailure(
                "/cases", listed.status_code, listed.text,
                listed.extensions["probe_elapsed_seconds"],
            ) from exc
        if not cases:
            raise ApiSubstepFailure(
                "/cases", listed.status_code, listed.text,
                listed.extensions["probe_elapsed_seconds"],
            )
        case_id = cases[0]["case_id"]
        progress(
            "API_LIST_END", endpoint="/cases", status_code=listed.status_code,
            case_count=len(cases), case_id=case_id,
        )

        case_endpoint = f"/cases/{case_id}"
        progress("API_GET_CASE_START", endpoint=case_endpoint, case_id=case_id)
        opened = await _request(client, "GET", case_endpoint)
        case = _payload(opened, case_endpoint)
        progress(
            "API_GET_CASE_END", endpoint=case_endpoint, status_code=opened.status_code,
            case_id=case_id,
        )

        evidence = _case_evidence(case)
        if not evidence:
            raise ApiSubstepFailure(
                case_endpoint, opened.status_code, opened.text,
                opened.extensions["probe_elapsed_seconds"],
            )
        evidence_id = evidence[0]["evidence_id"]
        evidence_endpoint = f"/evidence/{evidence_id}"
        progress("API_EVIDENCE_START", endpoint=evidence_endpoint, evidence_id=evidence_id)
        resolved = await _request(client, "GET", evidence_endpoint)
        progress(
            "API_EVIDENCE_END", endpoint=evidence_endpoint, status_code=resolved.status_code,
            evidence_id=evidence_id,
        )

        review_endpoint = f"/cases/{case_id}/review"
        progress("API_REVIEW_START", endpoint=review_endpoint, case_id=case_id)
        reviewed = await _request(
            client, "POST", review_endpoint,
            json={"decision": "escalate", "note": "deadline probe"},
        )
        progress(
            "API_REVIEW_END", endpoint=review_endpoint, status_code=reviewed.status_code,
            case_id=case_id,
        )
        return {
            "api_upload_status": upload.status_code,
            "api_list_status": listed.status_code,
            "api_get_case_status": opened.status_code,
            "api_evidence_status": resolved.status_code,
            "evidence_resolution_count": 1,
            "review_status": reviewed.status_code,
            "investigation_id": investigation_id,
            "case_id": case_id,
        }


async def _api_lifecycle(ctx: dict[str, Any], progress: Callable[..., Any]) -> dict[str, Any]:
    import audit_compiler.api.app as api_module

    return await _run_api_lifecycle(ctx, progress, api_module.app)


def api_lifecycle(ctx: dict[str, Any], progress: Callable[..., Any]) -> dict[str, Any]:
    return asyncio.run(_api_lifecycle(ctx, progress))


def parse_timeout_overrides(values: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--stage-timeout requires STAGE=SECONDS")
        name, raw = value.rsplit("=", 1)
        seconds = float(raw)
        if seconds <= 0:
            raise ValueError("stage timeout must be positive")
        result[name] = seconds
    return result


def discover_controls(allowlist: list[str] | None) -> list[str]:
    from audit_compiler.controls.registry import select_controls

    selected, _ = select_controls(tuple(allowlist) if allowlist is not None else None)
    return [control.id for control in selected]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dossier", default=os.environ.get("EVIDENTIA_SAMPLE_DOSSIER"))
    parser.add_argument("--stage-timeout", action="append", default=[], metavar="STAGE=SECONDS")
    parser.add_argument("--controls", nargs="+", help="explicit registered-control allowlist")
    parser.add_argument("--max-total-seconds", type=float, default=120.0)
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--verbose", action="store_true")
    return parser


def _write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, indent=2, default=_json_default) + "\n", encoding="utf-8"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dossier:
        print("--dossier or EVIDENTIA_SAMPLE_DOSSIER is required", file=sys.stderr)
        return 2
    if args.max_total_seconds <= 0:
        print("--max-total-seconds must be positive", file=sys.stderr)
        return 2
    try:
        overrides = parse_timeout_overrides(args.stage_timeout)
        controls = discover_controls(args.controls)
    except (ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    unknown = sorted(set(overrides) - set(DEFAULT_TIMEOUTS))
    if unknown:
        print(f"unknown timeout stage(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    budgets = {**DEFAULT_TIMEOUTS, **overrides}
    started = time.monotonic()
    stage_elapsed: dict[str, float] = {}
    aggregate: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="evidentia-e2e-probe-") as workspace:
        root = Path(workspace)
        ctx: dict[str, Any] = {
            "dossier": args.dossier,
            "workspace": workspace,
            "controls": controls,
            "engagement_id": "deadline-probe",
            "run_id": f"run-{os.getpid()}",
            "parsed_artifact": str(root / "parsed.pickle"),
            "database": str(root / "probe.duckdb"),
            "cases_artifact": str(root / "cases.json"),
            "verbose": args.verbose,
        }
        stages = [
            Stage(
                "validate_dossier_path",
                "validate_dossier_path",
                budgets["validate_dossier_path"],
                validate_path,
            ),
            Stage(
                "inventory_and_hash", "inventory_and_hash", budgets["inventory_and_hash"], inventory
            ),
            Stage(
                "native_parse_and_canonical_compile",
                "native_parse_and_canonical_compile",
                budgets["native_parse_and_canonical_compile"],
                native_compile,
            ),
            Stage(
                "duckdb_persistence",
                "duckdb_persistence",
                budgets["duckdb_persistence"],
                persist_duckdb,
            ),
        ]
        stages += [
            Stage("registered_control", control_id, budgets["control"], run_control)
            for control_id in controls
        ]
        stages += [
            Stage(
                "admission_and_case_building",
                "admission_and_case_building",
                budgets["admission_and_case_building"],
                admission_cases,
            ),
            Stage(
                "api_lifecycle",
                "api_lifecycle",
                budgets["api_lifecycle"],
                api_lifecycle,
            ),
        ]
        try:
            for stage in stages:
                total_remaining = args.max_total_seconds - (time.monotonic() - started)
                if total_remaining <= 0:
                    raise ProbeFailure(
                        {
                            "status": "timeout",
                            "stage": "total",
                            "component": stage.component,
                            "budget_seconds": args.max_total_seconds,
                            "elapsed_seconds": time.monotonic() - started,
                            "last_progress_event": None,
                            "child_pid": None,
                            "stack_dump_emitted": False,
                            "suggested_next_command": _suggested_command(ctx, stage.component),
                        }
                    )
                effective = Stage(
                    stage.name, stage.component, min(stage.budget, total_remaining), stage.target
                )
                if stage.name == "registered_control":
                    ctx["current_control"] = stage.component
                result = execute_stage(effective, ctx)
                stage_elapsed[stage.component] = result.pop("elapsed_seconds")
                aggregate.update(result)
        except ProbeFailure as exc:
            _write_report(args.json_report, exc.report)
            return 1
    report = {
        "status": "success",
        "total_elapsed_seconds": time.monotonic() - started,
        "stage_elapsed_seconds": stage_elapsed,
        "controls_executed": controls,
        "cases_produced": aggregate.get("cases_produced", 0),
        "verdict_counts": aggregate.get("verdict_counts", {}),
        "evidence_resolution_count": aggregate.get("evidence_resolution_count", 0),
        "api_status": {key: value for key, value in aggregate.items() if key.startswith("api_")},
        "review_status": aggregate.get("review_status"),
    }
    emit("PROBE_SUCCESS", **report)
    _write_report(args.json_report, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
