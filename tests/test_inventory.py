import hashlib
import json
from pathlib import Path

from audit_compiler.cli import main
from audit_compiler.inventory import inventory_dossier, sha256_file


def test_sha256_file_and_inventory_are_stable(tmp_path: Path) -> None:
    dossier = tmp_path / "dossier"
    nested = dossier / "nested"
    nested.mkdir(parents=True)
    first = dossier / "source.csv"
    second = nested / "note.txt"
    first.write_bytes(b"alpha")
    second.write_bytes(b"beta")

    assert sha256_file(first) == hashlib.sha256(b"alpha").hexdigest()
    manifest = inventory_dossier(dossier)
    assert [item.path for item in manifest.files] == ["nested/note.txt", "source.csv"]
    assert [item.file_type for item in manifest.files] == ["text", "csv"]


def test_cli_writes_machine_readable_manifest(tmp_path: Path) -> None:
    dossier = tmp_path / "dossier"
    dossier.mkdir()
    (dossier / "source.xml").write_text("<root />", encoding="utf-8")
    output = tmp_path / "manifest.json"

    main(["inventory", str(dossier), "--output", str(output)])

    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1.0"
    assert manifest["files"][0]["path"] == "source.xml"
    assert manifest["files"][0]["file_type"] == "xml"
