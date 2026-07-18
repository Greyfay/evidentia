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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from audit_compiler.agent.context import AgentContext
from audit_compiler.agent.store import get_store
from audit_compiler.api.investigations import router as investigations_router
from audit_compiler.compiler import CompileRequest as CompilerRequest
from audit_compiler.compiler import CompilerService
from audit_compiler.inventory import _FILE_TYPES

# Individual source files the dossier compiler can parse, plus a packaged .zip archive.
_SUPPORTED_UPLOAD_SUFFIXES = set(_FILE_TYPES) | {".zip"}

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


def _compile(path: Path, *, name: str | None = None) -> dict:
    return CompilerService().compile(
        CompilerRequest(dossier=path, name=name)
    ).model_dump(mode="json")


def _bundle() -> dict:
    if _STATE["bundle"] is None:
        default = os.environ.get("EVIDENTIA_DOSSIER")
        if default and Path(default).exists():
            _STATE["bundle"] = _compile(Path(default))
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
    _STATE["bundle"] = _compile(path, name=request.name)
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


def _safe_dossier_name(filename: str | None) -> str:
    """Return the bare filename, rejecting any path component that could escape the dir."""

    name = Path(filename or "").name
    if not name or name.startswith("."):
        raise HTTPException(400, f"uploaded file has an unusable name: {filename!r}")
    return name


async def _stream_upload(upload: object, dest: Path, budget: list[int]) -> None:
    """Stream one upload to ``dest``, enforcing the shared byte budget across all files."""

    with dest.open("wb") as out:
        while chunk := await upload.read(1024 * 1024):  # type: ignore[attr-defined]
            budget[0] += len(chunk)
            if budget[0] > _MAX_UPLOAD_BYTES:
                raise HTTPException(400, "upload exceeds the maximum allowed size")
            out.write(chunk)
    await upload.close()  # type: ignore[attr-defined]


@app.post("/engagements/upload")
async def upload_engagement(request: Request) -> dict:
    # Accept files under any form field name (the FE sends "files"; older clients "file").
    # multi_items() preserves every entry when a field name repeats (multiple files).
    form = await request.form()
    uploads = [value for _name, value in form.multi_items() if not isinstance(value, str)]
    if not uploads:
        raise HTTPException(400, "no file uploaded")

    suffixes = [Path(u.filename or "").suffix.lower() for u in uploads]
    for upload, suffix in zip(uploads, suffixes, strict=True):
        if suffix not in _SUPPORTED_UPLOAD_SUFFIXES:
            raise HTTPException(400, f"unsupported file type: {upload.filename!r}")
    if ".zip" in suffixes and len(uploads) > 1:
        raise HTTPException(400, "a .zip archive must be uploaded on its own")

    # The dossier must outlive this request (tools run against it across many investigation
    # steps), so it lives in its own temp dir; clean it up only if compilation never happens.
    persist_dir = Path(tempfile.mkdtemp(prefix="evidentia-dossier-"))
    try:
        budget = [0]
        with tempfile.TemporaryDirectory(prefix="evidentia-upload-") as tmp:
            tmp_path = Path(tmp)
            if suffixes == [".zip"]:
                zip_path = tmp_path / "upload.zip"
                await _stream_upload(uploads[0], zip_path, budget)
                extract_dir = tmp_path / "extracted"
                extract_dir.mkdir()
                try:
                    with zipfile.ZipFile(zip_path) as zf:
                        _safe_extract(zf, extract_dir)
                except zipfile.BadZipFile as exc:
                    raise HTTPException(400, "uploaded file is not a valid zip archive") from exc
                shutil.copytree(_find_dossier_root(extract_dir), persist_dir, dirs_exist_ok=True)
            else:
                # One or more individual source files are themselves the dossier.
                for upload in uploads:
                    await _stream_upload(
                        upload, persist_dir / _safe_dossier_name(upload.filename), budget
                    )

        bundle = _compile(persist_dir)
        ctx = AgentContext.from_compiled_run(
            persist_dir / ".admissible" / "audit.duckdb",
            bundle["engagement"]["engagement_id"],
            bundle["engagement"]["run_id"],
        )
        engagement_id = get_store().add_engagement(None, ctx, bundle)
        return {"engagement_id": engagement_id, "engagement": bundle["engagement"]}
    except BaseException:
        shutil.rmtree(persist_dir, ignore_errors=True)
        raise
