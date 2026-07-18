"""FastAPI review API over the compiled engagement (see docs/CASES_SCHEMA.md).

Endpoints mirror the auditor workflow: compile a dossier, list cases, open a case's replay
bundle, jump to an exact evidence pointer, and record a human review decision.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

try:  # load local secrets before reading env; harmless if python-dotenv/.env absent
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from audit_compiler.agent.context import AgentContext
from audit_compiler.agent.store import get_store
from audit_compiler.api.investigations import router as investigations_router
from audit_compiler.pipeline import compile_engagement

app = FastAPI(title="Evidentia", summary="Provenance-first evidence compiler for auditors")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.include_router(investigations_router)

_STATE: dict[str, dict] = {"bundle": None}
_MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MiB: generous for a dossier, bounded against abuse


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


def _safe_extract(zf: zipfile.ZipFile, target_dir: Path) -> None:
    """Extract ``zf`` into ``target_dir``, rejecting any entry that could escape it.

    Rejects absolute paths, ``..`` traversal (checked by resolving each member's final path
    and requiring it stay under ``target_dir``), and symlinks (a symlink member could point
    outside the target dir after extraction even though its own path looks safe).
    """

    target_dir = target_dir.resolve()
    for member in zf.infolist():
        name = member.filename
        if not name or name.startswith("/") or name.startswith("\\"):
            raise HTTPException(400, f"unsafe path in zip entry: {name!r}")
        # Symlinks: the upper 16 bits of external_attr hold the Unix mode when set by a
        # Unix zipper; S_ISLNK on that mode catches "file that is actually a symlink".
        mode = member.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise HTTPException(400, f"symlink entries are not allowed: {name!r}")
        member_path = (target_dir / name).resolve()
        if member_path != target_dir and target_dir not in member_path.parents:
            raise HTTPException(400, f"zip entry escapes target directory: {name!r}")
    zf.extractall(target_dir)


def _find_dossier_root(extract_dir: Path) -> Path:
    """The dossier root is the extracted dir itself, or its single top-level folder."""

    entries = [p for p in extract_dir.iterdir() if not p.name.startswith("__MACOSX")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extract_dir


@app.post("/engagements/upload")
async def upload_engagement(file: UploadFile) -> dict:
    if file.filename and not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "only .zip uploads are supported")

    with tempfile.TemporaryDirectory(prefix="evidentia-upload-") as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "upload.zip"
        size = 0
        with zip_path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > _MAX_UPLOAD_BYTES:
                    raise HTTPException(400, "upload exceeds the maximum allowed size")
                out.write(chunk)
        await file.close()

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        try:
            with zipfile.ZipFile(zip_path) as zf:
                _safe_extract(zf, extract_dir)
        except zipfile.BadZipFile as exc:
            raise HTTPException(400, "uploaded file is not a valid zip archive") from exc

        dossier_root = _find_dossier_root(extract_dir)

        # The dossier must outlive this request (tools run against it across many
        # investigation steps), so copy it out of the auto-cleaned temp dir.
        persist_dir = Path(tempfile.mkdtemp(prefix="evidentia-dossier-"))
        shutil.copytree(dossier_root, persist_dir, dirs_exist_ok=True)

    bundle = compile_engagement(persist_dir)
    ctx = AgentContext.from_dossier_path(persist_dir)
    engagement_id = get_store().add_engagement(None, ctx, bundle)
    return {"engagement_id": engagement_id, "engagement": bundle["engagement"]}
