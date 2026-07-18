"""Mutation test: renaming the supporting files must not change the verdicts.

If detection depended on filenames instead of content and columns, renaming the sources
would break it. The controls must generalise, so the four schemes must still be found.
"""

from __future__ import annotations

import shutil

from audit_compiler.pipeline import compile_engagement


def test_renaming_supporting_files_preserves_findings(sample_dossier, tmp_path):
    mutated = tmp_path / "mutated_dossier"
    shutil.copytree(sample_dossier, mutated)

    # Rename every non-GDPdU supporting file to an opaque name (GDPdU files are driven by
    # index.xml URLs, so only their folders' index remains authoritative).
    counter = 0
    for path in sorted(mutated.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".csv", ".xlsx", ".docx", ".pdf"}:
            counter += 1
            path.rename(path.with_name(f"source_{counter:03d}{path.suffix.lower()}"))

    bundle = compile_engagement(mutated, name="mutated")
    confirmed = {c["control_id"] for c in bundle["cases"] if c["verdict"] == "CONFIRMED"}
    assert {"vendor_sod", "split_payment", "capitalisation", "cutoff"} <= confirmed
    assert any(c["verdict"] == "DISMISSED" for c in bundle["cases"])
