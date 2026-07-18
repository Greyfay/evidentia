"""Source dossier inventory and content hashing."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

_FILE_TYPES = {
    ".csv": "csv",
    ".txt": "text",
    ".xml": "xml",
    ".xlsx": "xlsx",
    ".xls": "xls",
    ".docx": "docx",
    ".pdf": "pdf",
}


class _ImmutableManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceFile(_ImmutableManifestModel):
    path: str = Field(min_length=1)
    file_type: str = Field(min_length=1)
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class DossierManifest(_ImmutableManifestModel):
    schema_version: str = "1.0"
    generated_at: datetime
    files: tuple[SourceFile, ...]


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest of a file without loading it fully into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_file_type(path: Path) -> str:
    """Infer a generic native file type from an extension, without filename rules."""

    return _FILE_TYPES.get(path.suffix.lower(), "unknown")


def inventory_dossier(directory: Path) -> DossierManifest:
    """Recursively inventory regular files in a dossier directory in stable order."""

    root = directory.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"dossier directory does not exist: {directory}")
    if not root.is_dir():
        raise NotADirectoryError(f"dossier path is not a directory: {directory}")

    files = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        files.append(
            SourceFile(
                path=path.relative_to(root).as_posix(),
                file_type=infer_file_type(path),
                byte_size=path.stat().st_size,
                sha256=sha256_file(path),
            )
        )
    return DossierManifest(generated_at=datetime.now(UTC), files=tuple(files))
