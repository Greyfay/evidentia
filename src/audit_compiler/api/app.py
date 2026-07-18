"""FastAPI review API over the compiled engagement (see docs/CASES_SCHEMA.md).

Endpoints mirror the auditor workflow: compile a dossier, list cases, open a case's replay
bundle, jump to an exact evidence pointer, and record a human review decision.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # load local secrets before reading env; harmless if python-dotenv/.env absent
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from audit_compiler.pipeline import compile_engagement

app = FastAPI(title="Evidentia", summary="Provenance-first evidence compiler for auditors")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

_STATE: dict[str, dict] = {"bundle": None}


class CompileRequest(BaseModel):
    dossier_path: str
    name: str | None = None


class ReviewRequest(BaseModel):
    decision: str  # confirm | dismiss | request_evidence | escalate
    note: str | None = None


def _bundle() -> dict:
    if _STATE["bundle"] is None:
        default = os.environ.get("EVIDENTIA_DOSSIER")
        if default and Path(default).exists():
            _STATE["bundle"] = compile_engagement(Path(default))
        else:
            raise HTTPException(404, "No engagement compiled. POST /engagements/compile first.")
    return _STATE["bundle"]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/engagements/compile")
def compile_endpoint(request: CompileRequest) -> dict:
    path = Path(request.dossier_path).expanduser()
    if not path.exists():
        raise HTTPException(400, f"dossier path does not exist: {request.dossier_path}")
    _STATE["bundle"] = compile_engagement(path, name=request.name)
    return _STATE["bundle"]["engagement"]


@app.get("/cases")
def list_cases() -> dict:
    bundle = _bundle()
    return {"engagement": bundle["engagement"], "cases": bundle["cases"]}


@app.get("/cases/{case_id}")
def get_case(case_id: str) -> dict:
    case = next((c for c in _bundle()["cases"] if c["case_id"] == case_id), None)
    if case is None:
        raise HTTPException(404, "case not found")
    return case


@app.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: str) -> dict:
    for case in _bundle()["cases"]:
        pools = [e for step in case["evidence_chain"] for e in step["evidence"]]
        pools += case["calculation"]["evidence"]
        pools += [e for ct in case["counter_tests"] for e in ct["evidence"]]
        match = next((e for e in pools if e["evidence_id"] == evidence_id), None)
        if match is not None:
            return match
    raise HTTPException(404, "evidence not found")


@app.post("/cases/{case_id}/review")
def review_case(case_id: str, request: ReviewRequest) -> dict:
    case = next((c for c in _bundle()["cases"] if c["case_id"] == case_id), None)
    if case is None:
        raise HTTPException(404, "case not found")
    case["reviewer_decision"] = {"decision": request.decision, "note": request.note}
    return case
